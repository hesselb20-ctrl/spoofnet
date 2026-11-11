"""Tests for the parts that only matter for recorded phone logs: broadcast ephemeris,
the motion summary from raw IMU samples, and GnssLogger quirks."""
import numpy as np
import pytest

from spoofnet import geo
from spoofnet.io import rinex_nav
from spoofnet.io.gnsslogger import imu_summary, read_log

# One GPS record in RINEX 3 layout (values from a public broadcast file, 19 May 2024).
NAV = """     3.04           NAVIGATION DATA     M                   RINEX VERSION / TYPE
                                                            END OF HEADER
G01 2024 05 19 02 00 00 2.724379301071e-04-5.115907697473e-12 0.000000000000e+00
     6.300000000000e+01 8.912500000000e+01 5.698451649099e-09-2.677548634191e+00
     4.600733518600e-06 1.340045360848e-02 7.828697562218e-06 5.153763977051e+03
     7.200000000000e+03 1.173466444016e-07 7.032944872669e-02-1.117587089539e-07
     9.549570557831e-01 2.247187500000e+02 1.030999446842e+00-7.885328455581e-09
     3.007268121931e-10 1.000000000000e+00 2.315000000000e+03 0.000000000000e+00
     2.800000000000e+00 6.300000000000e+01-1.955777406693e-08 6.300000000000e+01
     1.800000000000e+01 4.000000000000e+00
R05 2024 05 19 00 15 00 1.000000000000e-05 0.000000000000e+00 0.000000000000e+00
     1.000000000000e+04 1.000000000000e+00 0.000000000000e+00 0.000000000000e+00
     1.000000000000e+04 1.000000000000e+00 0.000000000000e+00 1.000000000000e+00
     1.000000000000e+04 1.000000000000e+00 0.000000000000e+00 0.000000000000e+00
"""


def test_rinex_nav_parses_and_gives_a_gps_orbit(tmp_path):
    f = tmp_path / "brdc.rnx"
    f.write_text(NAV)
    nav = rinex_nav.read_nav(f)
    assert list(nav) == [("G", 1)]                      # GLONASS records are skipped cleanly
    e = nav[("G", 1)][0]
    assert e.toe == 7200.0 and e.toc == 7200.0 and e.sqrt_a == pytest.approx(5153.763977051)
    t = np.array([7200.0, 7201.0, 9000.0])
    pos, clk = rinex_nav.sat_state(e, t)
    radius = np.linalg.norm(pos, axis=1)
    assert np.all((radius > 2.60e7) & (radius < 2.70e7))            # GPS orbit radius
    speed = np.linalg.norm(pos[1] - pos[0])
    assert 2500.0 < speed < 3400.0                                  # ECEF speed of a GPS satellite, m/s
    assert clk[0] == pytest.approx(2.724379301071e-04 + 1.955777406693e-08, abs=5e-8)   # af0 - TGD + relativity


def test_attach_makes_pseudoranges_fit_the_simple_model(tmp_path):
    """Build pseudoranges from the full model (flight time, Earth rotation, satellite clock)
    and check that `attach` reduces them to |sat - x| + b."""
    f = tmp_path / "brdc.rnx"
    f.write_text(NAV)
    e = rinex_nav.read_nav(f)[("G", 1)][0]
    from spoofnet.data import MeasurementSet
    n = 5
    t_rx = 7300.0 + np.arange(n)
    rx = geo.lla_to_ecef(43.5, 16.4, 20.0)
    # find a time when the satellite is above this receiver's horizon is not needed: geometry only
    pr = np.zeros(n)
    for i in range(n):
        tau = 0.075
        for _ in range(5):
            p, clk = rinex_nav.sat_state(e, np.array([t_rx[i] - tau]))
            th = 7.2921151467e-5 * tau
            p = np.array([np.cos(th) * p[0, 0] + np.sin(th) * p[0, 1], -np.sin(th) * p[0, 0] + np.cos(th) * p[0, 1], p[0, 2]])
            tau = np.linalg.norm(p - rx) / geo.C
        pr[i] = np.linalg.norm(p - rx) - geo.C * clk[0] + 123.0        # 123 m of receiver clock
    z = np.zeros(n)
    ms = MeasurementSet(
        t=np.arange(n, dtype=float), t0_gps=7300.0, sig_const=np.array([0]), sig_svid=np.array([1]),
        sig_band=np.array([0]), sig_sub=np.array([0]), sig_sat=np.array([0]), cn0=np.full((n, 1), 40.0),
        pr=pr[:, None].copy(), prr=np.zeros((n, 1)), az=np.full((n, 1), np.nan), el=np.full((n, 1), 90.0),
        agc=np.full((n, 2), np.nan), clk_disc=np.zeros(n, dtype=int), fix_ecef=np.tile(rx, (n, 1)),
        fix_vel=np.zeros((n, 3)), fix_acc=np.ones(n), net_ecef=np.full((n, 3), np.nan), net_acc=np.full(n, np.nan),
        imu_vib=z, imu_acc_h=z, imu_yaw=z, imu_tilt=z, meta={"t_rx_tow": t_rx}, truth={})
    rep = rinex_nav.attach(ms, {("G", 1): [e]})
    assert rep["with_ephemeris"] == 1
    model = np.linalg.norm(ms.sat_pos[:, 0] - rx, axis=1) + 123.0 - 2.3      # troposphere term at zenith
    assert np.max(np.abs(ms.pr[:, 0] - model)) < 0.05
    assert 2500.0 < np.linalg.norm(ms.sat_vel[0, 0]) < 3400.0


def test_imu_summary_from_raw_samples():
    hz, n = 50, 20
    t_ms = 1_700_000_000_000 + np.arange(n * hz) * (1000.0 / hz)
    acc = np.column_stack([t_ms, np.zeros(n * hz), np.zeros(n * hz), np.full(n * hz, 9.81)])
    gyr = np.column_stack([t_ms, np.zeros(n * hz), np.zeros(n * hz), np.full(n * hz, 0.2)])
    s = imu_summary(acc, gyr, t_ms[0], n)
    assert np.all(s["vib"] < 1e-6) and np.all(s["acc_h"] < 1e-6) and np.all(s["tilt"] < 1e-6)
    assert np.allclose(s["yaw"], 0.2, atol=1e-6)                     # rotation about gravity
    # The phone is turned onto its side at second 10: a tilt event, then quiet again.
    acc2 = acc.copy()
    late = acc2[:, 0] >= t_ms[0] + 10_000
    acc2[late, 1], acc2[late, 3] = 9.81, 0.0
    s2 = imu_summary(acc2, gyr, t_ms[0], n)
    assert s2["tilt"][10:13].max() > 20.0 and s2["tilt"][:9].max() < 1.0 and s2["tilt"][-1] < 5.0
    assert np.isnan(imu_summary(acc[:3], gyr[:3], t_ms[0], n)["vib"]).all()   # too few samples: unknown, not "still"


def test_reader_handles_gnsslogger_quirks(tmp_path):
    """Status lines without a time, FLP fixes, and Galileo without a decoded time of week."""
    path = tmp_path / "quirks.txt"
    bias = -1451520000000000000
    lines = [
        "# Raw,utcTimeMillis,TimeNanos,FullBiasNanos,BiasNanos,Svid,State,ReceivedSvTimeNanos,Cn0DbHz,"
        "PseudorangeRateMetersPerSecond,CarrierFrequencyHz,ConstellationType,AgcDb,HardwareClockDiscontinuityCount",
        "# Status,UnixTimeMillis,SignalCount,SignalIndex,ConstellationType,Svid,CarrierFrequencyHz,Cn0DbHz,AzimuthDegrees,ElevationDegrees",
        "# Fix,Provider,LatitudeDegrees,LongitudeDegrees,AltitudeMeters,SpeedMps,AccuracyMeters,BearingDegrees,UnixTimeMillis",
    ]
    for k in range(3):
        t_ns = 1000000000000 + k * 1000000000
        utc = 1700000000000 + k * 1000
        lines.append(f"Raw,{utc},{t_ns},{bias},0.0,5,16399,{t_ns - 70000000},41.5,-120.5,1575420030,1,-1.5,0")
        # Galileo with only the secondary-code lock: transmit time known modulo 100 ms
        lines.append(f"Raw,{utc},{t_ns},{bias},0.0,11,2048,{(t_ns - 80000000) % 100000000},38.0,55.0,1575420030,6,-1.5,0")
        lines.append("Status,,2,0,1,5,1575420030,41.5,120.0,55.0")
        lines.append(f"Fix,FLP,43.5,16.4,10.0,0.0,5.0,,{utc}")
        lines.append(f"Fix,GPS,43.5,16.4,10.0,1.0,4.0,90.0,{utc}")
    path.write_text("\n".join(lines) + "\n")
    ms = read_log(path)
    assert ms.n_epochs == 3 and ms.n_signals == 2
    g, e = int(np.flatnonzero(ms.sig_const == 0)[0]), int(np.flatnonzero(ms.sig_const == 1)[0])
    assert ms.pr[0, g] == pytest.approx(0.07 * geo.C, rel=1e-9)
    assert ms.pr[0, e] == pytest.approx(0.08 * geo.C, rel=1e-9)
    assert np.all(ms.el[:, g] == 55.0)                               # status matched without a timestamp
    assert np.all(np.isfinite(ms.fix_ecef)) and np.all(np.isnan(ms.net_ecef))   # FLP is not a network fix
    assert ms.meta["has_agc"] is False                                # present but never changes
    assert ms.agc[0, 0] == -1.5
