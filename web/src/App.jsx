import React, { useEffect, useMemo, useState } from 'react'
import { supabase, VIEWER_EMAIL } from './supabaseClient'
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts'

const REGIONS = [{ id: 'US', label: 'USA (Amazon.com)' }, { id: 'CA', label: 'Canada (Amazon.ca)' }]
const pct = (x) => (x == null ? '—' : (x * 100).toFixed(1) + '%')
const num = (x) => (x == null ? '—' : Number(x).toLocaleString())
const money = (x, r) => (x == null ? '—' : (r === 'CA' ? 'C$' : '$') + Number(x).toFixed(0))

// centralized chart tokens (light theme — mirror styles.css)
const C = { grid: '#ece7de', axis: '#9a938a', tip: '#ffffff', line: '#0f766e',
  muted: '#a89f92', green: '#15803d', warn: '#c2410c', violet: '#4f46e5', neon: '#0f766e' }
const REDUCED = typeof window !== 'undefined' &&
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const tipStyle = { background: C.tip, border: '1px solid ' + C.grid, borderRadius: 10, color: '#1c1a17', boxShadow: '0 6px 18px rgba(28,26,23,.08)' }
const axisTick = { fill: C.axis, fontSize: 11 }

function toCSV(rows) {
  if (!rows.length) return ''
  const cols = Object.keys(rows[0])
  const esc = (v) => (v == null ? '' : /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v))
  return [cols.join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n')
}
function download(name, rows) {
  const blob = new Blob([toCSV(rows)], { type: 'text/csv' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; a.click()
  URL.revokeObjectURL(a.href)
}
function isAuthErr(e) {
  const m = (e && (e.message || e.code || '')).toString().toLowerCase()
  return m.includes('jwt') || m.includes('token') || m.includes('401') || m.includes('expired')
}
async function fetchAll(table, filters = {}) {
  let q = supabase.from(table).select('*')
  for (const [k, v] of Object.entries(filters)) q = q.eq(k, v)
  const { data, error } = await q.limit(50000)
  if (error) { if (isAuthErr(error)) await supabase.auth.signOut(); throw error }
  return data || []
}
// keyword search — server-side filter/sort on query_summary (73k rows, don't fetch all)
async function searchQueries(region, { text, category, view }) {
  let q = supabase.from('query_summary').select('*').eq('region', region)
  if (text) q = q.ilike('search_query', `%${text}%`)
  if (category && category !== 'All') q = q.eq('top_category', category)
  if (view === 'rising') q = q.eq('trend', 'Rising')
  else if (view === 'emerging') q = q.eq('trend', 'Emerging')
  else if (view === 'attack') q = q.gte('latest_volume', 1000).lt('our_purchase_share', 0.05).gt('our_purchase_share', -1)
  const orderCol = view === 'volume' || view === 'rising' || view === 'emerging' || view === 'attack' ? 'latest_volume' : 'our_purchases_12mo'
  q = q.order(orderCol, { ascending: false, nullsFirst: false }).limit(150)
  const { data, error } = await q
  if (error) { if (isAuthErr(error)) await supabase.auth.signOut(); throw error }
  return data || []
}

// small data hook with loading + error
function useRows(table, filters) {
  const key = JSON.stringify([table, filters])
  const [s, setS] = useState({ rows: [], loading: true, error: null })
  useEffect(() => {
    let alive = true; setS((p) => ({ ...p, loading: true, error: null }))
    fetchAll(table, filters)
      .then((rows) => alive && setS({ rows, loading: false, error: null }))
      .catch((e) => alive && setS({ rows: [], loading: false, error: e.message || 'Failed to load data' }))
    return () => { alive = false }
  }, [key]) // eslint-disable-line
  return s
}

/* ---------- shared state UI ---------- */
const Icon = ({ d }) => (
  <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>)
const DL = 'M12 3v12m0 0l4-4m-4 4l-4-4M4 21h16' // download glyph
const Empty = ({ msg }) => (
  <div className="state" role="status">
    <Icon d="M3 3h18v18H3zM3 9h18M9 21V9" />
    <div>{msg || 'No data for this selection.'}</div>
  </div>)
const ErrorBanner = ({ msg, onRetry }) => (
  <div className="banner" role="alert">
    <span>⚠ {msg}</span>
    {onRetry && <button className="ghost" onClick={onRetry}>Retry</button>}
  </div>)
const SkelChart = () => <div className="skel chart" aria-hidden="true" />
const SkelRows = ({ n = 5 }) => <div aria-hidden="true">{Array.from({ length: n }).map((_, i) =>
  <div className="skel" key={i} style={{ width: (90 - i * 8) + '%' }} />)}</div>

/* ---------------- Login gate (the "code" = shared account password) ---------------- */
function Login({ onIn }) {
  const [pw, setPw] = useState(''); const [email, setEmail] = useState(VIEWER_EMAIL)
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  const go = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    const { error } = await supabase.auth.signInWithPassword({ email, password: pw })
    setBusy(false); if (error) setErr('That code didn’t work. Check it and try again.'); else onIn()
  }
  return (
    <div className="login">
      <h1 style={{ marginBottom: 14 }}>SQP Explorer <small className="muted">LifePro · US &amp; Canada</small></h1>
      <form className="card" onSubmit={go}>
        <h3>Enter access code</h3>
        <div className="field" style={{ marginBottom: 10 }}>
          <label htmlFor="lg-email">Email</label>
          <input id="lg-email" type="email" autoComplete="username" value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="lg-code">Access code</label>
          <input id="lg-code" type="password" autoComplete="current-password" value={pw}
                 onChange={(e) => setPw(e.target.value)} autoFocus
                 aria-invalid={!!err} aria-describedby={err ? 'lg-err' : undefined} />
        </div>
        <button className="primary" style={{ width: '100%', marginTop: 12 }} disabled={busy || !pw}>
          {busy ? <><span className="spin" /> Checking…</> : 'Enter'}
        </button>
        {err && <div className="err" id="lg-err" role="alert">{err}</div>}
        <div className="muted small" style={{ marginTop: 10 }}>
          Search-query-performance (SQP) share data. Figures are search-attributed, not total units.
        </div>
      </form>
    </div>
  )
}

/* ---------------- Dashboard ---------------- */
function Dashboard({ region }) {
  const { rows, loading, error } = useRows('category_month', { region })
  const [cat, setCat] = useState('Vibration Plate')
  const cats = useMemo(() => [...new Set(rows.map((r) => r.category))].sort(), [rows])
  useEffect(() => { if (cats.length && !cats.includes(cat)) setCat(cats[0]) }, [cats]) // eslint-disable-line
  const series = useMemo(() => rows.filter((r) => r.category === cat)
    .sort((a, b) => a.month.localeCompare(b.month)), [rows, cat])
  const last = series[series.length - 1] || {}
  if (error) return <ErrorBanner msg={error} />
  return (
    <div>
      <div className="controls">
        <div className="field">
          <label htmlFor="dash-cat">Category</label>
          <select id="dash-cat" value={cat} onChange={(e) => setCat(e.target.value)} disabled={loading}>
            {cats.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
      </div>
      <div className="kpis" style={{ marginBottom: 16 }}>
        <div className="kpi"><div className="v">{loading ? '…' : pct(last.our_purchase_share)}</div><div className="l">Our purchase share (latest)</div></div>
        <div className="kpi"><div className="v">{loading ? '…' : num(last.our_purchases)}</div><div className="l">Our purchases (latest mo)</div></div>
        <div className="kpi"><div className="v">{loading ? '…' : money(last.our_median_price, region)}</div><div className="l">Our median price</div></div>
        <div className="kpi"><div className="v">{loading ? '…' : pct(last.price_vs_niche)}</div><div className="l">Price vs niche</div></div>
      </div>
      <div className="card">
        <h3>Our purchase share over time — {cat}</h3>
        {loading ? <SkelChart /> : !series.length ? <Empty /> : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={series} margin={{ left: -10 }}>
              <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={axisTick} />
              <YAxis tickFormatter={(v) => (v * 100).toFixed(0) + '%'} tick={axisTick} />
              <Tooltip formatter={(v) => pct(v)} contentStyle={tipStyle} />
              <Line type="monotone" dataKey="our_purchase_share" stroke={C.line} strokeWidth={2}
                    dot={false} name="Purchase share" isAnimationActive={!REDUCED} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      <div className="grid two">
        <div className="card">
          <h3>Share funnel: impression → click → ATC → purchase</h3>
          {loading ? <SkelChart /> : !series.length ? <Empty /> : (
            <ResponsiveContainer width="100%" height={230}>
              <LineChart data={series} margin={{ left: -10 }}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                <XAxis dataKey="month" tick={axisTick} />
                <YAxis tickFormatter={(v) => (v * 100).toFixed(0) + '%'} tick={axisTick} />
                <Tooltip formatter={(v) => pct(v)} contentStyle={tipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line dataKey="our_impr_share" stroke={C.muted} dot={false} name="Impr" isAnimationActive={!REDUCED} />
                <Line dataKey="our_click_share" stroke={C.line} dot={false} name="Click" isAnimationActive={!REDUCED} />
                <Line dataKey="our_atc_share" stroke={C.warn} dot={false} name="ATC" isAnimationActive={!REDUCED} />
                <Line dataKey="our_purchase_share" stroke={C.green} strokeWidth={2} dot={false} name="Purchase" isAnimationActive={!REDUCED} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <h3>Our price vs niche median price</h3>
          {loading ? <SkelChart /> : !series.length ? <Empty /> : (
            <ResponsiveContainer width="100%" height={230}>
              <LineChart data={series} margin={{ left: -10 }}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                <XAxis dataKey="month" tick={axisTick} />
                <YAxis tick={axisTick} />
                <Tooltip contentStyle={tipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line dataKey="niche_median_price" stroke={C.muted} dot={false} name="Niche" isAnimationActive={!REDUCED} />
                <Line dataKey="our_median_price" stroke={C.line} strokeWidth={2} dot={false} name="Ours" isAnimationActive={!REDUCED} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  )
}

/* ---------------- Categories (what category has what) ---------------- */
function Categories({ region }) {
  const { rows: fams, loading, error } = useRows('family_summary', { region })
  const [open, setOpen] = useState(null)
  const byCat = useMemo(() => {
    const m = {}
    for (const f of fams) {
      const c = (m[f.category] = m[f.category] || { category: f.category, families: 0, asins: 0, purchases: 0, rows: [] })
      c.families++; c.asins += f.asins || 0; c.purchases += f.purchases_12mo || 0; c.rows.push(f)
    }
    return Object.values(m).sort((a, b) => b.purchases - a.purchases)
  }, [fams])
  const toggle = (c) => setOpen(open === c ? null : c)
  return (
    <div className="card">
      <h3>Categories — what we sell where ({region})</h3>
      {error && <ErrorBanner msg={error} />}
      {loading ? <SkelRows n={8} /> : !byCat.length ? <Empty /> : (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Category</th><th className="num">Families</th><th className="num">ASINs</th><th className="num">Our purchases (12mo)</th><th aria-label="expand" /></tr></thead>
            <tbody>
              {byCat.map((c) => {
                const isOpen = open === c.category
                return (
                  <React.Fragment key={c.category}>
                    <tr className="rowbtn" tabIndex={0} role="button" aria-expanded={isOpen}
                        onClick={() => toggle(c.category)}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(c.category) } }}>
                      <td><b>{c.category}</b></td>
                      <td className="num">{c.families}</td>
                      <td className="num">{c.asins}</td>
                      <td className="num">{num(c.purchases)}</td>
                      <td className="muted small" aria-hidden="true">{isOpen ? '▲' : '▼'}</td>
                    </tr>
                    {isOpen && [...c.rows].sort((a, b) => b.purchases_12mo - a.purchases_12mo).map((f) => (
                      <tr key={f.family} style={{ background: 'var(--panel2)' }}>
                        <td style={{ paddingLeft: 26 }} className="muted">↳ {f.family}</td>
                        <td className="num muted">{f.asins}</td>
                        <td className="num muted">{num(f.impressions)} impr</td>
                        <td className="num">{num(f.purchases_12mo)} · <span className="muted">{pct(f.mkt_share_in_its_queries)} mkt</span></td>
                        <td><span className={'badge ' + (f.trajectory === 'growing' ? 'up' : f.trajectory === 'declining' ? 'down' : 'flat')}>{f.trajectory}</span></td>
                      </tr>
                    ))}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="muted small" style={{ marginTop: 10 }}>Click (or focus + Enter) a category to expand its families. "mkt" = our share of that family's search queries.</div>
    </div>
  )
}

/* ---------------- ASIN Explorer ---------------- */
function AsinExplorer({ region }) {
  const { rows: catalog, loading: cl, error: ce } = useRows('catalog', { region })
  const [asin, setAsin] = useState('')
  useEffect(() => { if (catalog.length && !catalog.find((c) => c.asin === asin)) setAsin(catalog[0].asin) }, [catalog]) // eslint-disable-line
  const { rows: raw, loading: rl, error: re } = useRows('asin_month', asin ? { region, asin } : { region, asin: '__none__' })
  const rows = useMemo(() => [...raw].sort((a, b) => a.month.localeCompare(b.month)), [raw])
  const options = useMemo(() => [...catalog].sort((a, b) => (a.category + a.family).localeCompare(b.category + b.family)), [catalog])
  const meta = catalog.find((c) => c.asin === asin) || {}
  const total = rows.reduce((s, r) => s + (r.purchases || 0), 0)
  const error = ce || re
  return (
    <div>
      {error && <ErrorBanner msg={error} />}
      <div className="controls">
        <div className="field">
          <label htmlFor="asin-sel">ASIN</label>
          <select id="asin-sel" value={asin} onChange={(e) => setAsin(e.target.value)} style={{ minWidth: 320 }} disabled={cl}>
            {options.map((c) => <option key={c.asin} value={c.asin}>{c.asin} — {c.family} ({c.category})</option>)}
          </select>
        </div>
      </div>
      <div className="kpis" style={{ marginBottom: 16 }}>
        <div className="kpi"><div className="v">{rl ? '…' : num(total)}</div><div className="l">Purchases (12mo, core)</div></div>
        <div className="kpi"><div className="v">{meta.family || '—'}</div><div className="l">Family</div></div>
        <div className="kpi"><div className="v">{meta.category || '—'}</div><div className="l">Category</div></div>
        <div className="kpi"><div className="v">{meta.sku || meta.model || '—'}</div><div className="l">SKU</div></div>
      </div>
      <div className="card">
        <h3>Monthly purchases — {asin || '—'}</h3>
        {rl ? <SkelChart /> : !rows.length ? <Empty /> : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={rows} margin={{ left: -10 }}>
              <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={axisTick} />
              <YAxis tick={axisTick} />
              <Tooltip contentStyle={tipStyle} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line dataKey="purchases" stroke={C.green} strokeWidth={2} dot={false} name="Purchases (core)" isAnimationActive={!REDUCED} />
              <Line dataKey="clicks" stroke={C.line} dot={false} name="Clicks" isAnimationActive={!REDUCED} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

/* ---------------- Downloads ---------------- */
function Downloads({ region }) {
  const [busy, setBusy] = useState(''); const [err, setErr] = useState('')
  const dl = async (table, name) => {
    setBusy(table); setErr('')
    try { const rows = await fetchAll(table, { region }); download(`${region}_${name}.csv`, rows) }
    catch (e) { setErr(e.message || 'Download failed') }
    finally { setBusy('') }
  }
  const Btn = ({ table, name, label, primary }) => (
    <button className={primary ? 'primary' : ''} disabled={!!busy}
            aria-busy={busy === table} onClick={() => dl(table, name)}>
      {busy === table ? <><span className="spin" /> Preparing…</> : <><Icon d={DL} />{label}</>}
    </button>)
  return (
    <div className="card">
      <h3>Downloads — {region}</h3>
      <p className="muted small">Exports the current region as CSV. All figures are core-niche, search-attributed SQP.</p>
      {err && <ErrorBanner msg={err} />}
      <div className="grid two">
        <div><Btn table="asin_month" name="asin_level_monthly" label="ASIN-level monthly" primary />
          <div className="muted small" style={{ marginTop: 6 }}>region · asin · category · family · month · impressions/clicks/cart_adds/purchases</div></div>
        <div><Btn table="category_month" name="category_level_monthly" label="Category-level monthly" primary />
          <div className="muted small" style={{ marginTop: 6 }}>market + our funnel shares + prices per category per month</div></div>
        <div><Btn table="family_summary" name="family_summary" label="Family summary (12mo)" /></div>
        <div><Btn table="catalog" name="catalog" label="Catalog (ASIN → category map)" /></div>
      </div>
    </div>
  )
}

/* ---------------- Keyword Explorer ---------------- */
const trendBadge = (t) => 'badge ' + (t === 'Rising' || t === 'Emerging' ? 'up' : t === 'Declining' || t === 'Fading' ? 'down' : 'flat')

function KeywordDetail({ region, q, onClose }) {
  const { rows: months, loading: ml } = useRows('query_month', { region, search_query: q })
  const { rows: asinRows, loading: al } = useRows('query_asin_month', { region, search_query: q })
  const series = useMemo(() => [...months].sort((a, b) => a.month.localeCompare(b.month)), [months])
  const byAsin = useMemo(() => {
    const m = {}
    for (const r of asinRows) {
      const a = (m[r.asin] = m[r.asin] || { asin: r.asin, family: r.family, category: r.category, purchases: 0, clicks: 0, impressions: 0 })
      a.purchases += r.asin_purchases || 0; a.clicks += r.asin_clicks || 0; a.impressions += r.asin_impressions || 0
    }
    return Object.values(m).sort((x, y) => y.purchases - x.purchases).slice(0, 10)
  }, [asinRows])
  return (
    <div className="card" style={{ borderColor: 'var(--cyan)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <h3 style={{ margin: 0 }}>▸ “{q}”</h3>
        <button className="ghost" onClick={onClose}>Close</button>
      </div>
      <div className="grid two" style={{ marginTop: 14 }}>
        <div>
          <div className="muted small" style={{ marginBottom: 8, letterSpacing: '.16em', textTransform: 'uppercase' }}>Search volume vs our purchase share</div>
          {ml ? <SkelChart /> : !series.length ? <Empty /> : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={series} margin={{ left: -6 }}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                <XAxis dataKey="month" tick={axisTick} />
                <YAxis yAxisId="v" tick={axisTick} tickFormatter={(v) => v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v} />
                <YAxis yAxisId="s" orientation="right" tick={axisTick} tickFormatter={(v) => (v * 100).toFixed(0) + '%'} />
                <Tooltip contentStyle={tipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line yAxisId="v" dataKey="search_query_volume" stroke={C.violet} dot={false} name="Volume" isAnimationActive={!REDUCED} />
                <Line yAxisId="s" dataKey="our_purchase_share" stroke={C.neon || C.green} strokeWidth={2} dot={false} name="Our share" isAnimationActive={!REDUCED} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div>
          <div className="muted small" style={{ marginBottom: 8, letterSpacing: '.16em', textTransform: 'uppercase' }}>Which of our ASINs win this query</div>
          {al ? <SkelRows n={5} /> : !byAsin.length ? <Empty msg="No ASIN captured this query" /> : (
            <div className="table-scroll"><table>
              <thead><tr><th>ASIN</th><th>Family</th><th className="num">Purch</th><th className="num">Clicks</th></tr></thead>
              <tbody>{byAsin.map((a) => (
                <tr key={a.asin}><td>{a.asin}</td><td className="muted">{a.family}</td>
                  <td className="num">{num(a.purchases)}</td><td className="num muted">{num(a.clicks)}</td></tr>))}
              </tbody></table></div>
          )}
        </div>
      </div>
    </div>
  )
}

function KeywordExplorer({ region }) {
  const [text, setText] = useState(''); const [debounced, setDebounced] = useState('')
  const [category, setCategory] = useState('All'); const [view, setView] = useState('purchases')
  const [cats, setCats] = useState(['All']); const [sel, setSel] = useState(null)
  const [state, setState] = useState({ rows: [], loading: true, error: null })
  useEffect(() => { const t = setTimeout(() => setDebounced(text), 300); return () => clearTimeout(t) }, [text])
  useEffect(() => { fetchAll('category_month', { region })
    .then((d) => setCats(['All', ...[...new Set(d.map((r) => r.category))].sort()])).catch(() => {}) }, [region])
  useEffect(() => {
    let alive = true; setState((s) => ({ ...s, loading: true, error: null }))
    searchQueries(region, { text: debounced, category, view })
      .then((rows) => alive && setState({ rows, loading: false, error: null }))
      .catch((e) => alive && setState({ rows: [], loading: false, error: e.message || 'Search failed' }))
    return () => { alive = false }
  }, [region, debounced, category, view])
  const VIEWS = [['purchases', 'Most purchases'], ['volume', 'Top volume'], ['rising', 'Rising'], ['emerging', 'Emerging'], ['attack', 'Attack list']]
  const { rows, loading, error } = state
  return (
    <div>
      {sel && <KeywordDetail region={region} q={sel} onClose={() => setSel(null)} />}
      <div className="controls">
        <div className="field" style={{ flex: 1, minWidth: 220 }}>
          <label htmlFor="kw-search">Search keywords</label>
          <input id="kw-search" value={text} onChange={(e) => setText(e.target.value)}
                 placeholder="e.g. lymphatic drainage" autoComplete="off" />
        </div>
        <div className="field">
          <label htmlFor="kw-cat">Category</label>
          <select id="kw-cat" value={category} onChange={(e) => setCategory(e.target.value)}>
            {cats.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
      </div>
      <div className="tabs" role="tablist" aria-label="Keyword views" style={{ marginBottom: 14 }}>
        {VIEWS.map(([id, label]) => (
          <button key={id} className={'tab' + (view === id ? ' active' : '')} role="tab"
                  aria-selected={view === id} onClick={() => setView(id)}>{label}</button>))}
      </div>
      <div className="card">
        <h3>{view === 'attack' ? 'Attack list — high volume, low share (<5%)' : 'Keywords'} · {region}</h3>
        {error && <ErrorBanner msg={error} />}
        {loading ? <SkelRows n={10} /> : !rows.length ? <Empty msg="No keywords match." /> : (
          <div className="table-scroll"><table>
            <thead><tr><th>Keyword</th><th>Category</th><th className="num">Volume/mo</th>
              <th className="num">Our share</th><th className="num">Our purch (12mo)</th><th>Trend</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.search_query} className="rowbtn" tabIndex={0} role="button"
                  onClick={() => setSel(r.search_query)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(r.search_query) } }}>
                <td><b>{r.search_query}</b></td>
                <td className="muted small">{r.top_category}</td>
                <td className="num">{num(r.latest_volume)}</td>
                <td className="num">{pct(r.our_purchase_share)}</td>
                <td className="num">{num(r.our_purchases_12mo)}</td>
                <td><span className={trendBadge(r.trend)}>{r.trend}</span></td>
              </tr>))}
            </tbody></table></div>
        )}
        <div className="muted small" style={{ marginTop: 10 }}>Showing up to 150 · click a keyword for its trend + which ASINs win it. Volumes are whole-market (all queries our ASINs appear in).</div>
      </div>
    </div>
  )
}

/* ---------------- Family Explorer ---------------- */
const AREA_COLORS = ['#0f766e', '#c2410c', '#d97706', '#4f46e5', '#be185d', '#15803d', '#0891b2', '#7c3aed']
const shortKw = (k) => (k && k.length > 22 ? k.slice(0, 21) + '…' : k)
const kfmt = (v) => (v >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : v >= 1e3 ? (v / 1e3).toFixed(0) + 'k' : v)

function FamilyExplorer({ region }) {
  const { rows: niche, loading: nl, error: ne } = useRows('family_niche_month', { region })
  const families = useMemo(() => [...new Set(niche.map((r) => r.family))].sort(), [niche])
  const [family, setFamily] = useState('')
  useEffect(() => { if (families.length && !families.includes(family)) setFamily(families[0]) }, [families]) // eslint-disable-line
  const { rows: comp, loading: cl } = useRows('family_kw_composition', family ? { region, family } : { region, family: '__none__' })
  const { rows: tk, loading: tl } = useRows('family_top_keywords', family ? { region, family } : { region, family: '__none__' })
  const series = useMemo(() => niche.filter((r) => r.family === family).sort((a, b) => a.month.localeCompare(b.month)), [niche, family])
  const last = series[series.length - 1] || {}
  const our12 = series.reduce((s, r) => s + (r.our_purchases || 0), 0)
  const { keywords, stack } = useMemo(() => {
    const months = [...new Set(comp.map((r) => r.month))].sort()
    const tot = {}; comp.forEach((r) => { tot[r.keyword] = (tot[r.keyword] || 0) + r.volume })
    let kws = Object.keys(tot).filter((k) => k !== 'Other').sort((a, b) => tot[b] - tot[a])
    if (tot['Other'] != null) kws.push('Other')
    const bm = Object.fromEntries(months.map((m) => [m, { month: m }]))
    comp.forEach((r) => { bm[r.month][r.keyword] = r.volume })
    return { keywords: kws, stack: months.map((m) => bm[m]) }
  }, [comp])
  if (ne) return <ErrorBanner msg={ne} />
  return (
    <div>
      <div className="controls">
        <div className="field" style={{ minWidth: 240 }}>
          <label htmlFor="fam-sel">Product family</label>
          <select id="fam-sel" value={family} onChange={(e) => setFamily(e.target.value)} disabled={nl}>
            {families.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
      </div>
      <div className="kpis" style={{ marginBottom: 16 }}>
        <div className="kpi"><div className="v">{nl ? '…' : kfmt(last.niche_volume)}</div><div className="l">Niche size (searches/mo)</div></div>
        <div className="kpi"><div className="v">{nl ? '…' : pct(last.our_niche_purchase_share)}</div><div className="l">Our niche share (latest)</div></div>
        <div className="kpi"><div className="v">{nl ? '…' : num(our12)}</div><div className="l">Our purchases (12mo)</div></div>
        <div className="kpi"><div className="v">{nl ? '…' : num(last.n_queries)}</div><div className="l">Keywords in niche</div></div>
      </div>
      <div className="card">
        <h3>Niche movement — volume by top keyword · {family}</h3>
        {cl ? <SkelChart /> : !stack.length ? <Empty /> : (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={stack} margin={{ left: -4 }}>
              <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={axisTick} />
              <YAxis tick={axisTick} tickFormatter={kfmt} />
              <Tooltip contentStyle={tipStyle} formatter={(v, n) => [num(v), n]} />
              <Legend wrapperStyle={{ fontSize: 10 }} formatter={shortKw} />
              {keywords.map((k, i) => (
                <Area key={k} type="monotone" dataKey={k} stackId="1" name={k}
                      stroke={k === 'Other' ? '#cfc7ba' : AREA_COLORS[i % AREA_COLORS.length]}
                      fill={k === 'Other' ? '#d8d1c6' : AREA_COLORS[i % AREA_COLORS.length]}
                      fillOpacity={k === 'Other' ? 0.5 : 0.55} isAnimationActive={!REDUCED} />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        )}
        <div className="muted small" style={{ marginTop: 8 }}>Stacked area = the niche's total search volume, divided across its top keywords (rest = “Other”). Height rising/falling shows the niche growing/shrinking.</div>
      </div>
      <div className="card">
        <h3>Our market share within the niche · {family}</h3>
        {nl ? <SkelChart /> : !series.length ? <Empty /> : (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={series} margin={{ left: -10 }}>
              <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={axisTick} />
              <YAxis tick={axisTick} tickFormatter={(v) => (v * 100).toFixed(1) + '%'} />
              <Tooltip contentStyle={tipStyle} formatter={(v) => pct(v)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line dataKey="our_niche_purchase_share" stroke={C.neon || C.green} strokeWidth={2} dot={false} name="Our purchase share" isAnimationActive={!REDUCED} />
              <Line dataKey="our_niche_impr_share" stroke={C.muted} dot={false} name="Our impression share" isAnimationActive={!REDUCED} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      <div className="card">
        <h3>Top keywords · {family}</h3>
        {tl ? <SkelRows n={8} /> : !tk.length ? <Empty /> : (
          <div className="table-scroll"><table>
            <thead><tr><th>Keyword</th><th className="num">Volume/mo</th><th className="num">Our share</th><th className="num">Our purch (12mo)</th><th>Trend</th></tr></thead>
            <tbody>{[...tk].sort((a, b) => b.our_purchases_12mo - a.our_purchases_12mo).map((r) => (
              <tr key={r.search_query}>
                <td><b>{r.search_query}</b></td>
                <td className="num">{num(r.latest_volume)}</td>
                <td className="num">{pct(r.our_purchase_share)}</td>
                <td className="num">{num(r.our_purchases_12mo)}</td>
                <td><span className={trendBadge(r.trend)}>{r.trend}</span></td>
              </tr>))}
            </tbody></table></div>
        )}
      </div>
    </div>
  )
}

/* ---------------- Ads (paid, by family) — Canada only ---------------- */
function AdsExplorer() {
  const { rows, loading, error } = useRows('v_ad_family_month', { region: 'CA' })
  const [prog, setProg] = useState('SP'); const [family, setFamily] = useState('All')
  const fr = useMemo(() => rows.filter((r) => prog === 'All' || r.program === prog), [rows, prog])
  const families = useMemo(() => ['All', ...[...new Set(fr.filter((r) => r.family).map((r) => r.family))].sort()], [fr])
  useEffect(() => { if (!families.includes(family)) setFamily('All') }, [families]) // eslint-disable-line
  const scope = useMemo(() => family === 'All' ? fr : fr.filter((r) => r.family === family), [fr, family])
  const series = useMemo(() => {
    const m = {}
    scope.forEach((r) => { const x = (m[r.month] = m[r.month] || { month: r.month, spend: 0, sales: 0 }); x.spend += r.spend || 0; x.sales += r.sales || 0 })
    return Object.values(m).sort((a, b) => a.month.localeCompare(b.month)).map((x) => ({ ...x, acos: x.sales ? x.spend / x.sales : null }))
  }, [scope])
  const famTable = useMemo(() => {
    const m = {}
    fr.filter((r) => r.family).forEach((r) => { const x = (m[r.family] = m[r.family] || { family: r.family, spend: 0, sales: 0, clicks: 0 }); x.spend += r.spend || 0; x.sales += r.sales || 0; x.clicks += r.clicks || 0 })
    return Object.values(m).map((x) => ({ ...x, acos: x.sales ? x.spend / x.sales : null })).sort((a, b) => b.spend - a.spend)
  }, [fr])
  const tot = scope.reduce((s, r) => ({ spend: s.spend + (r.spend || 0), sales: s.sales + (r.sales || 0) }), { spend: 0, sales: 0 })
  if (error) return <ErrorBanner msg={error} />
  return (
    <div>
      <div className="controls">
        <div className="field"><label htmlFor="ad-prog">Program</label>
          <select id="ad-prog" value={prog} onChange={(e) => setProg(e.target.value)}>
            <option value="SP">Sponsored Products</option><option value="SB">Sponsored Brands</option><option value="All">All</option>
          </select></div>
        <div className="field"><label htmlFor="ad-fam">Family</label>
          <select id="ad-fam" value={family} onChange={(e) => setFamily(e.target.value)}>{families.map((f) => <option key={f}>{f}</option>)}</select></div>
        <span className="muted small" style={{ alignSelf: 'flex-end' }}>Canada · Vendor Central ads</span>
      </div>
      <div className="kpis" style={{ marginBottom: 16 }}>
        <div className="kpi"><div className="v">{loading ? '…' : money(tot.spend, 'CA')}</div><div className="l">Ad spend (12mo)</div></div>
        <div className="kpi"><div className="v">{loading ? '…' : money(tot.sales, 'CA')}</div><div className="l">Ad sales</div></div>
        <div className="kpi"><div className="v">{loading ? '…' : (tot.sales ? (tot.spend / tot.sales * 100).toFixed(0) + '%' : '—')}</div><div className="l">ACOS</div></div>
        <div className="kpi"><div className="v">{loading ? '…' : (families.length - 1)}</div><div className="l">Families advertised</div></div>
      </div>
      <div className="card"><h3>Spend &amp; ACOS over time · {family}</h3>
        {loading ? <SkelChart /> : !series.length ? <Empty /> : (
          <ResponsiveContainer width="100%" height={260}><LineChart data={series} margin={{ left: -6 }}>
            <CartesianGrid stroke={C.grid} strokeDasharray="3 3" /><XAxis dataKey="month" tick={axisTick} />
            <YAxis yAxisId="s" tick={axisTick} tickFormatter={kfmt} /><YAxis yAxisId="a" orientation="right" tick={axisTick} tickFormatter={(v) => (v * 100).toFixed(0) + '%'} />
            <Tooltip contentStyle={tipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
            <Line yAxisId="s" dataKey="spend" stroke={C.violet} strokeWidth={2} dot={false} name="Spend" isAnimationActive={!REDUCED} />
            <Line yAxisId="a" dataKey="acos" stroke={C.warn} dot={false} name="ACOS" isAnimationActive={!REDUCED} />
          </LineChart></ResponsiveContainer>)}
      </div>
      <div className="card"><h3>Families by ad spend</h3>
        {loading ? <SkelRows n={8} /> : (
          <div className="table-scroll"><table>
            <thead><tr><th>Family</th><th className="num">Spend</th><th className="num">Sales</th><th className="num">ACOS</th></tr></thead>
            <tbody>{famTable.map((r) => (
              <tr key={r.family} className="rowbtn" onClick={() => setFamily(r.family)}>
                <td><b>{r.family}</b></td><td className="num">{money(r.spend, 'CA')}</td>
                <td className="num">{money(r.sales, 'CA')}</td>
                <td className="num"><span className={'badge ' + (r.acos > 0.25 ? 'down' : 'up')}>{r.acos ? (r.acos * 100).toFixed(0) + '%' : '—'}</span></td></tr>))}
            </tbody></table></div>)}
      </div>
    </div>
  )
}

/* ---------------- Campaign Map (editable, read-write) ---------------- */
function CampaignMapping() {
  const [rows, setRows] = useState([]); const [loading, setLoading] = useState(true); const [err, setErr] = useState(null)
  const [statusF, setStatusF] = useState('needs'); const [q, setQ] = useState(''); const [saved, setSaved] = useState('')
  const load = () => { setLoading(true); fetchAll('campaign_map', { region: 'CA' })
    .then((d) => { setRows(d.sort((a, b) => (b.spend || 0) - (a.spend || 0))); setLoading(false) })
    .catch((e) => { setErr(e.message); setLoading(false) }) }
  useEffect(load, [])
  const families = useMemo(() => [...new Set(rows.filter((r) => r.auto_family).map((r) => r.auto_family))].sort(), [rows])
  const filtered = useMemo(() => rows.filter((r) => {
    const eff = r.manual_family || r.auto_family
    const need = statusF === 'all' ? true : statusF === 'mapped' ? !!eff : !eff || r.status === 'brand-level'
    const txt = !q || (r.campaign_name || '').toLowerCase().includes(q.toLowerCase())
    return need && txt
  }), [rows, statusF, q])
  const save = async (row, val) => {
    const { error } = await supabase.from('campaign_map').update({ manual_family: val })
      .eq('program', row.program).eq('campaign_id', row.campaign_id)
    if (error) { setErr(error.message); if (isAuthErr(error)) supabase.auth.signOut(); return }
    setRows((rs) => rs.map((r) => (r.program === row.program && r.campaign_id === row.campaign_id ? { ...r, manual_family: val } : r)))
    setSaved(row.campaign_id + ''); setTimeout(() => setSaved(''), 1200)
  }
  const needCount = rows.filter((r) => !(r.manual_family || r.auto_family) || r.status === 'brand-level').length
  return (
    <div>
      <div className="controls">
        <div className="field" style={{ flex: 1, minWidth: 220 }}><label htmlFor="cm-q">Search campaign</label>
          <input id="cm-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="campaign name…" /></div>
        <div className="field"><label htmlFor="cm-f">Show</label>
          <select id="cm-f" value={statusF} onChange={(e) => setStatusF(e.target.value)}>
            <option value="needs">Needs mapping ({needCount})</option><option value="mapped">Mapped</option><option value="all">All</option>
          </select></div>
      </div>
      <div className="card">
        <h3>Campaign → Family mapping · Canada {saved && <span className="badge up">saved ✓</span>}</h3>
        {err && <ErrorBanner msg={err} onRetry={load} />}
        {loading ? <SkelRows n={10} /> : !filtered.length ? <Empty msg="Nothing to map here 🎉" /> : (
          <div className="table-scroll"><table>
            <thead><tr><th>Campaign</th><th>Prog</th><th className="num">Spend</th><th>ASIN</th><th>Auto family</th><th>Override</th></tr></thead>
            <tbody>{filtered.slice(0, 200).map((r) => {
              const eff = r.manual_family || r.auto_family
              return (
                <tr key={r.program + r.campaign_id}>
                  <td style={{ maxWidth: 320 }}><span className="small">{r.campaign_name}</span></td>
                  <td className="small muted">{r.program}</td>
                  <td className="num">{money(r.spend, 'CA')}</td>
                  <td className="small muted">{r.asin || '—'}</td>
                  <td className="small">{r.auto_family || <span className="badge down">none</span>}</td>
                  <td>
                    <select value={r.manual_family || ''} onChange={(e) => save(r, e.target.value)}
                            style={{ minHeight: 34, borderColor: eff ? 'var(--line)' : 'var(--hot)' }}>
                      <option value="">{r.auto_family ? '(use auto)' : '— set family —'}</option>
                      {families.map((f) => <option key={f} value={f}>{f}</option>)}
                    </select>
                  </td>
                </tr>)
            })}</tbody></table></div>)}
        <div className="muted small" style={{ marginTop: 10 }}>Editing an override saves instantly to Supabase and the Ads views re-aggregate live. {needCount} campaign(s) need mapping. Showing up to 200.</div>
      </div>
    </div>
  )
}

/* ---------------- Ranks (organic rank, by family) ---------------- */
const rankBadge = (t) => 'badge ' + (t === 'Improving' || t === 'New' ? 'up' : t === 'Declining' || t === 'Lost' ? 'down' : 'flat')
const rk = (v) => (v == null ? '—' : '#' + (Number.isInteger(v) ? v : v.toFixed(0)))
function RanksExplorer({ region }) {
  const { rows: days, loading: dl, error: de } = useRows('rank_family_day', { region })
  const families = useMemo(() => [...new Set(days.map((r) => r.family))].sort(), [days])
  const [family, setFamily] = useState('')
  useEffect(() => { if (families.length && !families.includes(family)) setFamily(families[0]) }, [families]) // eslint-disable-line
  const { rows: kws, loading: kl } = useRows('rank_family_keyword', family ? { region, family } : { region, family: '__none__' })
  const series = useMemo(() => days.filter((r) => r.family === family).sort((a, b) => a.date.localeCompare(b.date)), [days, family])
  const last = series[series.length - 1] || {}
  const sortedKws = useMemo(() => [...kws].sort((a, b) => (a.latest_rank == null ? 1e6 : a.latest_rank) - (b.latest_rank == null ? 1e6 : b.latest_rank)), [kws])
  if (de) return <ErrorBanner msg={de} />
  return (
    <div>
      <div className="controls">
        <div className="field"><label htmlFor="rk-fam">Family</label>
          <select id="rk-fam" value={family} onChange={(e) => setFamily(e.target.value)} disabled={dl}>
            {families.map((f) => <option key={f}>{f}</option>)}</select></div>
        <span className="muted small" style={{ alignSelf: 'flex-end' }}>organic rank · last 30 days · lower = better</span>
      </div>
      <div className="kpis" style={{ marginBottom: 16 }}>
        <div className="kpi"><div className="v">{dl ? '…' : rk(last.median_rank)}</div><div className="l">Median organic rank</div></div>
        <div className="kpi"><div className="v">{dl ? '…' : num(last.kw_top10)}</div><div className="l">Keywords in top 10</div></div>
        <div className="kpi"><div className="v">{dl ? '…' : num(last.kw_ranked)}</div><div className="l">Keywords ranked</div></div>
        <div className="kpi"><div className="v">{dl ? '…' : num(last.kw_tracked)}</div><div className="l">Keywords tracked</div></div>
      </div>
      <div className="card">
        <h3>Ranking footprint over time · {family}</h3>
        {dl ? <SkelChart /> : !series.length ? <Empty /> : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={series} margin={{ left: -6 }}>
              <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={axisTick} minTickGap={28} tickFormatter={(d) => d.slice(5)} />
              <YAxis yAxisId="c" tick={axisTick} />
              <YAxis yAxisId="m" orientation="right" tick={axisTick} reversed />
              <Tooltip contentStyle={tipStyle} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line yAxisId="c" dataKey="kw_top10" stroke={C.line} strokeWidth={2} dot={false} name="In top 10" isAnimationActive={!REDUCED} />
              <Line yAxisId="c" dataKey="kw_top50" stroke={C.violet} dot={false} name="In top 50" isAnimationActive={!REDUCED} />
              <Line yAxisId="m" dataKey="median_rank" stroke={C.warn} dot={false} name="Median rank (right, inverted)" isAnimationActive={!REDUCED} />
            </LineChart>
          </ResponsiveContainer>
        )}
        <div className="muted small" style={{ marginTop: 8 }}>Left axis = # keywords ranking in top 10 / top 50. Right axis = median organic rank (inverted, so up = better).</div>
      </div>
      <div className="card">
        <h3>Keywords by organic rank · {family}</h3>
        {kl ? <SkelRows n={10} /> : !sortedKws.length ? <Empty /> : (
          <div className="table-scroll"><table>
            <thead><tr><th>Keyword</th><th className="num">Now</th><th className="num">Best</th><th className="num">Avg</th><th className="num">Ranked days</th><th>AC</th><th>Trend</th></tr></thead>
            <tbody>{sortedKws.slice(0, 200).map((r) => (
              <tr key={r.keyword}>
                <td><b>{r.keyword}</b></td>
                <td className="num">{rk(r.latest_rank)}</td>
                <td className="num">{rk(r.best_rank)}</td>
                <td className="num muted">{r.avg_rank == null ? '—' : r.avg_rank}</td>
                <td className="num muted">{r.days_ranked}/{r.days_tracked}</td>
                <td>{r.ac_badge ? <span className="badge up">AC</span> : ''}</td>
                <td><span className={rankBadge(r.trend)}>{r.trend}</span></td>
              </tr>))}
            </tbody></table></div>)}
        <div className="muted small" style={{ marginTop: 8 }}>“Now” = latest organic position (lower is better); blank = not ranked. Showing up to 200.</div>
      </div>
    </div>
  )
}

/* ---------------- App shell ---------------- */
export default function App() {
  const [authed, setAuthed] = useState(false); const [ready, setReady] = useState(false)
  const [tab, setTab] = useState('dash'); const [region, setRegion] = useState('US')
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => { setAuthed(!!data.session); setReady(true) })
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => setAuthed(!!session))
    return () => sub.subscription.unsubscribe()
  }, [])
  if (!ready) return <div className="app"><SkelRows n={4} /></div>
  if (!authed) return <Login onIn={() => setAuthed(true)} />
  const TABS = [['dash', 'Dashboard'], ['keyword', 'Keyword Explorer'], ['family', 'Family Explorer'], ['ranks', 'Ranks'], ['ads', 'Ads'], ['map', 'Campaign Map'], ['cats', 'Categories'], ['asin', 'ASIN Explorer'], ['dl', 'Downloads']]
  const SI = (d) => <svg viewBox="0 0 24 24"><path d={d} /></svg>
  const ICONS = {
    dash: <svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>,
    keyword: <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></svg>,
    family: SI('M4 18V9m5 9V5m5 13v-6m5 6V8'),
    ranks: SI('M4 20V8m5 12v-7m5 7V4m5 16v-9'),
    ads: SI('M3 12h4l3 8 4-16 3 8h4'),
    map: SI('M9 3l6 3 6-3v15l-6 3-6-3-6 3V6zM9 3v15M15 6v15'),
    cats: <svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M4 10h16" /></svg>,
    asin: SI('M20 7l-8-4-8 4 8 4 8-4zM4 7v10l8 4 8-4V7M12 11v10'),
    dl: SI('M12 3v12m0 0l4-4m-4 4l-4-4M5 21h14'),
  }
  return (
    <div className="app">
      <aside className="side">
        <div className="logo">SQP<b>·</b>Explorer</div>
        <nav className="snav" role="tablist" aria-label="Views">
          {TABS.map(([id, label]) => (
            <button key={id} className={'slink' + (tab === id ? ' on' : '')} role="tab"
                    aria-selected={tab === id} onClick={() => setTab(id)}>{ICONS[id]}<span>{label}</span></button>
          ))}
        </nav>
        <div className="side-foot">
          <div className="field"><label htmlFor="region-sel">Market</label>
            <select id="region-sel" value={region} onChange={(e) => setRegion(e.target.value)}>
              {REGIONS.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </div>
          <button className="ghost" onClick={() => supabase.auth.signOut()}>Sign out</button>
        </div>
      </aside>
      <main className="main">
        {tab === 'dash' && <Dashboard region={region} />}
        {tab === 'keyword' && <KeywordExplorer region={region} />}
        {tab === 'family' && <FamilyExplorer region={region} />}
        {tab === 'ranks' && <RanksExplorer region={region} />}
        {tab === 'ads' && <AdsExplorer />}
        {tab === 'map' && <CampaignMapping />}
        {tab === 'cats' && <Categories region={region} />}
        {tab === 'asin' && <AsinExplorer region={region} />}
        {tab === 'dl' && <Downloads region={region} />}
        <div className="muted small" style={{ marginTop: 20 }}>
          Data: Amazon Brand Analytics SQP · Jul 2025–Jun 2026 · search-attributed purchases (not total units; excludes 1P/Vendor).
        </div>
      </main>
    </div>
  )
}
