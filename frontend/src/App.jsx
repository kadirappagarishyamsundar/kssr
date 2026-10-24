import { useEffect, useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ReferenceLine,
} from "recharts";

const API = import.meta.env.VITE_API_URL || "";
const CUTOFFS = ["08:00", "09:00", "09:50", "10:00", "12:00"];
const mw = (v) => (v == null ? "–" : `${Math.round(v).toLocaleString()} MW`);

function useApi(url) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    if (!url) return;
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fetch(API + url)
      .then((r) => (r.ok ? r.json() : r.json().then((j) => Promise.reject(j.detail || r.statusText))))
      .then((data) => live && setState({ data, error: null, loading: false }))
      .catch((e) => live && setState({ data: null, error: String(e), loading: false }));
    return () => { live = false; };
  }, [url]);
  return state;
}

const Kpi = ({ v, l }) => <div className="kpi"><div className="v">{v}</div><div className="l">{l}</div></div>;
const Chart = ({ title, note, children }) => (
  <div className="card"><h2>{title}</h2><p>{note}</p>
    <ResponsiveContainer width="100%" height={280}>{children}</ResponsiveContainer></div>
);
const Status = ({ s }) => s.loading ? <div className="msg">Loading…</div> : s.error ? <div className="msg err">{s.error}</div> : null;

function ForecastPage({ cutoff, config }) {
  const [date, setDate] = useState("2026-01-10");
  const s = useApi(`/api/forecast?delivery_date=${date}&cutoff=${cutoff}`);
  const d = s.data;
  const rows = d?.hours.map((h) => ({ ...h, hour: new Date(h.startTime).getUTCHours() + ":00" }));
  return (
    <>
      <div className="controls">
        <label>Delivery day
          <input type="date" value={date} min={config.first_delivery_date} max={config.last_delivery_date}
                 onChange={(e) => e.target.value && setDate(e.target.value)} />
        </label>
      </div>
      <Status s={s} />
      {d && <>
        <div className="kpis">
          <Kpi v={new Date(d.latest_publish_used).toUTCString().slice(5, 22)} l="Latest forecast usable at cutoff (UTC)" />
          <Kpi v={mw(d.summary.mae_mw)} l="Mean absolute error this day" />
          <Kpi v={mw(d.summary.bias_mw)} l="Bias (+ = wind over-forecast)" />
          <Kpi v={mw(d.summary.mean_actual_mw)} l="Average actual wind" />
        </div>
        <Chart title={`Wind generation for ${d.delivery_date}`}
               note={`Forecast = the latest version published before ${new Date(d.cutoff_utc).toUTCString().slice(5, 22)} UTC on the day before. Later forecasts were not available when the buy was made.`}>
          <LineChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="hour" /><YAxis tickFormatter={(v) => `${v / 1000}GW`} />
            <Tooltip formatter={(v) => mw(v)} /><Legend />
            <Line type="monotone" dataKey="forecast_mw" name="Forecast at cutoff" stroke="#2563eb" dot={false} strokeWidth={2} />
            <Line type="monotone" dataKey="actual_mw" name="Actual" stroke="#059669" dot={false} strokeWidth={2} />
          </LineChart>
        </Chart>
      </>}
    </>
  );
}

function AccuracyPage({ cutoff }) {
  const sum = useApi(`/api/accuracy/summary?cutoff=${cutoff}`);
  const hour = useApi(`/api/accuracy/by-hour?cutoff=${cutoff}`);
  const hz = useApi("/api/accuracy/by-horizon");
  const dist = useApi(`/api/accuracy/error-distribution?cutoff=${cutoff}`);
  const s = sum.data;
  if (!s) return <Status s={sum} />;
  const bins = dist.data?.map((b) => ({ ...b, label: Math.round((b.bin_start + b.bin_end) / 2) }));
  return (
    <>
      <div className="kpis">
        <Kpi v={mw(s.mae_mw)} l={`Mean absolute error (${s.nmae_pct}% of average wind)`} />
        <Kpi v={mw(s.rmse_mw)} l="RMSE" />
        <Kpi v={mw(s.bias_mw)} l="Bias: forecast − actual" />
        <Kpi v={mw(s.error_p90_mw)} l="Shortfall buffer (90th percentile)" />
      </div>
      <div className="callout">
        Across {s.n_hours} delivery hours, the forecast available at the {cutoff} cutoff <b>over-stated wind by {mw(s.bias_mw)} on average</b>.
        In 9 hours out of 10 the shortfall was no more than <b>{mw(s.error_p90_mw)}</b>, so that is a reasonable extra volume to plan for.
        The bias is similar at every lead time, which suggests a level offset between the two Elexon datasets rather than poor forecasting skill.
      </div>
      <div className="grid2">
        {hour.data && <Chart title="Error by hour of day (UTC)" note="Mean absolute error and bias. Bias is largest overnight.">
          <BarChart data={hour.data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="hour" /><YAxis />
            <Tooltip formatter={(v) => mw(v)} /><Legend />
            <Bar dataKey="mae_mw" name="MAE" fill="#2563eb" /><Bar dataKey="bias_mw" name="Bias" fill="#d97706" /></BarChart>
        </Chart>}
        {hz.data && <Chart title="Error by forecast lead time" note="All forecast versions, grouped by hours between publishing and the target hour.">
          <BarChart data={hz.data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis />
            <Tooltip formatter={(v) => mw(v)} /><Legend />
            <Bar dataKey="mae_mw" name="MAE" fill="#2563eb" /><Bar dataKey="bias_mw" name="Bias" fill="#d97706" /></BarChart>
        </Chart>}
      </div>
      {bins && <Chart title="Distribution of forecast errors" note="Right of zero = less wind than forecast (buyer is short).">
        <BarChart data={bins}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis />
          <Tooltip labelFormatter={(l) => `≈ ${l} MW`} /><ReferenceLine x={bins.find((b) => b.bin_end >= 0)?.label} stroke="#dc2626" />
          <Bar dataKey="count" name="Hours" fill="#2563eb" /></BarChart>
      </Chart>}
    </>
  );
}

export default function App() {
  const [tab, setTab] = useState("forecast");
  const [cutoff, setCutoff] = useState("09:00");
  const cfg = useApi("/api/config");
  return (
    <>
      <header>
        <h1>Wind forecast accuracy<small>GB day-ahead buying · Elexon national wind · decisions made January 2026</small></h1>
        <div className="controls">
          <label>Decision cutoff (day before, London time)
            <select value={cutoff} onChange={(e) => setCutoff(e.target.value)}>
              {CUTOFFS.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <div className="tabs">
            <button className={tab === "forecast" ? "on" : ""} onClick={() => setTab("forecast")}>Forecast</button>
            <button className={tab === "accuracy" ? "on" : ""} onClick={() => setTab("accuracy")}>Accuracy</button>
          </div>
        </div>
      </header>
      <main>
        <Status s={cfg} />
        {cfg.data && (tab === "forecast" ? <ForecastPage cutoff={cutoff} config={cfg.data} /> : <AccuracyPage cutoff={cutoff} />)}
      </main>
    </>
  );
}
