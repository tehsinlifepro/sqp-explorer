import React, { useEffect, useMemo, useState } from 'react'
import { supabase, VIEWER_EMAIL } from './supabaseClient'
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts'

const REGIONS = [{ id: 'US', label: 'USA (Amazon.com)' }, { id: 'CA', label: 'Canada (Amazon.ca)' }]
const pct = (x) => (x == null ? '—' : (x * 100).toFixed(1) + '%')
const num = (x) => (x == null ? '—' : Number(x).toLocaleString())
const money = (x, r) => (x == null ? '—' : (r === 'CA' ? 'C$' : '$') + Number(x).toFixed(0))
const MON_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
const fmtMonth = (m) => { if (!m) return ''; const [y, mm] = String(m).split('-'); return `${MON_ABBR[(+mm) - 1] || mm} ${y}` }

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

/* ---------- sortable tables: useSort + <Th> (click any header to sort) ---------- */
function useSort(rows, initial) {
  const [sort, setSort] = useState(initial || { col: null, dir: 'desc' })
  const sorted = useMemo(() => {
    if (!sort.col) return rows
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = a[sort.col], bv = b[sort.col]
      const an = av == null || av === '', bn = bv == null || bv === ''
      if (an && bn) return 0
      if (an) return 1            // nulls / blanks always sort last
      if (bn) return -1
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir
    })
  }, [rows, sort])
  const toggle = (col) => setSort((s) => (s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'desc' }))
  return { sorted, sort, toggle }
}
const Th = ({ col, sort, toggle, children, num, ...p }) => (
  <th {...p} className={(num ? 'num ' : '') + 'sortable'} onClick={() => toggle(col)}
      aria-sort={sort.col === col ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
    {children}<span className="sortcaret">{sort.col === col ? (sort.dir === 'asc' ? '▲' : '▼') : ''}</span></th>)

/* ---------- Google-Sheets-style keyword filter: contains + multi-select ---------- */
function useKwFilter() {
  const [contains, setContains] = useState('')
  const [sel, setSel] = useState(() => new Set())
  const pred = (k) => (!contains || String(k).toLowerCase().includes(contains.toLowerCase())) && (sel.size === 0 || sel.has(k))
  const active = !!contains || sel.size > 0
  return { contains, setContains, sel, setSel, pred, active }
}
function KwFilter({ all, f }) {
  const [open, setOpen] = useState(false); const [find, setFind] = useState('')
  const shown = useMemo(() => all.filter((k) => !find || k.toLowerCase().includes(find.toLowerCase())), [all, find])
  return (
    <div className="field kwf">
      <label>Filter keywords</label>
      <div style={{ display: 'flex', gap: 6 }}>
        <input placeholder="contains…" value={f.contains} onChange={(e) => f.setContains(e.target.value)} style={{ minWidth: 150 }} />
        <button type="button" className="ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {f.sel.size ? f.sel.size + ' picked' : 'Pick ▾'}</button>
        {f.active && <button type="button" className="ghost" title="clear filter"
          onClick={() => { f.setContains(''); f.setSel(new Set()) }}>✕</button>}
      </div>
      {open && (
        <div className="popover" role="dialog" aria-label="Pick keywords">
          <input placeholder="search list…" value={find} onChange={(e) => setFind(e.target.value)} autoFocus />
          <div className="poprow">
            <button type="button" className="ghost small" onClick={() => f.setSel(new Set(shown))}>Select shown ({shown.length})</button>
            <button type="button" className="ghost small" onClick={() => f.setSel(new Set())}>Clear</button>
          </div>
          <div className="poplist">
            {shown.slice(0, 500).map((k) => (
              <label key={k} className="popitem">
                <input type="checkbox" checked={f.sel.has(k)} onChange={(e) => f.setSel((s) => {
                  const n = new Set(s); e.target.checked ? n.add(k) : n.delete(k); return n })} />
                <span>{k}</span></label>))}
            {!shown.length && <div className="muted small" style={{ padding: 8 }}>no matches</div>}
          </div>
          <button type="button" className="primary small" style={{ width: '100%' }} onClick={() => setOpen(false)}>Done</button>
        </div>)}
    </div>)
}

/* ---------- timeframe: month-range picker ---------- */
function useMonthRange(months) {
  const [from, setFrom] = useState(''); const [to, setTo] = useState('')
  const lo = months[0], hi = months[months.length - 1]
  useEffect(() => { setFrom(lo || ''); setTo(hi || '') }, [lo, hi])
  const inRange = (m) => (!from || m >= from) && (!to || m <= to)
  return { from, setFrom, to, setTo, inRange, months }
}
const MonthRange = ({ r }) => (
  <>
    <div className="field"><label>From month</label>
      <select value={r.from} onChange={(e) => r.setFrom(e.target.value)}>{r.months.map((m) => <option key={m}>{m}</option>)}</select></div>
    <div className="field"><label>To month</label>
      <select value={r.to} onChange={(e) => r.setTo(e.target.value)}>{r.months.map((m) => <option key={m}>{m}</option>)}</select></div>
  </>)
const maxN = (a, b) => (b == null ? a : a == null ? b : Math.max(a, b))  // max ignoring null

/* ---------------- Login gate (the "code" = shared account password) ---------------- */
function Login({ onIn }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  const go = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    const { error } = await supabase.auth.signInWithPassword({ email: VIEWER_EMAIL, password: pw })
    setBusy(false); if (error) setErr('That code didn’t work. Check it and try again.'); else onIn()
  }
  return (
    <div className="login">
      <h1 style={{ marginBottom: 14 }}>SQP Explorer <small className="muted">LifePro · US &amp; Canada</small></h1>
      <form className="card" onSubmit={go}>
        <h3>Enter access code</h3>
        {/* fixed shared account — hidden so password managers still pair the code, users only type the code */}
        <input type="email" autoComplete="username" value={VIEWER_EMAIL} readOnly aria-hidden="true"
               tabIndex={-1} style={{ position: 'absolute', width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />
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
        <div className="muted small" style={{ marginTop: 12 }}>
          Don’t have the access code? Message <b>Rana Momin</b> to get access.
        </div>
        <div className="muted small" style={{ marginTop: 8 }}>
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
  const months = useMemo(() => [...new Set(rows.filter((r) => r.category === cat).map((r) => r.month))].sort(), [rows, cat])
  const mr = useMonthRange(months)
  const series = useMemo(() => rows.filter((r) => r.category === cat && mr.inRange(r.month))
    .sort((a, b) => a.month.localeCompare(b.month)), [rows, cat, mr.from, mr.to])
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
        <MonthRange r={mr} />
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
  const { rows: fnm } = useRows('family_niche_month', { region })
  const [open, setOpen] = useState(null)
  const months = useMemo(() => [...new Set(fnm.map((r) => r.month))].sort(), [fnm])
  const mr = useMonthRange(months)
  const purByFam = useMemo(() => {
    const m = {}; fnm.forEach((r) => { if (mr.inRange(r.month)) m[r.family] = (m[r.family] || 0) + (r.our_purchases || 0) }); return m
  }, [fnm, mr.from, mr.to])
  const byCat = useMemo(() => {
    const m = {}
    for (const f of fams) {
      const p = purByFam[f.family] || 0
      const c = (m[f.category] = m[f.category] || { category: f.category, families: 0, asins: 0, purchases: 0, rows: [] })
      c.families++; c.asins += f.asins || 0; c.purchases += p; c.rows.push({ ...f, purchases_range: p })
    }
    return Object.values(m).sort((a, b) => b.purchases - a.purchases)
  }, [fams, purByFam])
  const { sorted, sort: sortState, toggle: sortBy } = useSort(byCat, { col: 'purchases', dir: 'desc' })
  const toggle = (c) => setOpen(open === c ? null : c)
  return (
    <div>
      <div className="controls"><MonthRange r={mr} /></div>
      <div className="card">
      <h3>Categories — what we sell where ({region})</h3>
      {error && <ErrorBanner msg={error} />}
      {loading ? <SkelRows n={8} /> : !byCat.length ? <Empty /> : (
        <div className="table-scroll">
          <table>
            <thead><tr>
              <Th col="category" sort={sortState} toggle={sortBy}>Category</Th>
              <Th col="families" sort={sortState} toggle={sortBy} num>Families</Th>
              <Th col="asins" sort={sortState} toggle={sortBy} num>ASINs</Th>
              <Th col="purchases" sort={sortState} toggle={sortBy} num>Our purchases (range)</Th>
              <th aria-label="expand" /></tr></thead>
            <tbody>
              {sorted.map((c) => {
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
                    {isOpen && [...c.rows].sort((a, b) => b.purchases_range - a.purchases_range).map((f) => (
                      <tr key={f.family} style={{ background: 'var(--panel2)' }}>
                        <td style={{ paddingLeft: 26 }} className="muted">↳ {f.family}</td>
                        <td className="num muted">{f.asins}</td>
                        <td className="num muted">{num(f.impressions)} impr</td>
                        <td className="num">{num(f.purchases_range)} · <span className="muted">{pct(f.mkt_share_in_its_queries)} mkt</span></td>
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
      <div className="muted small" style={{ marginTop: 10 }}>Click a category to expand its families. Purchases reflect the selected months; “mkt” share is 12-month.</div>
      </div>
    </div>
  )
}

/* ---------------- ASIN Explorer ---------------- */
function AsinExplorer({ region }) {
  const { rows: catalog, loading: cl, error: ce } = useRows('catalog', { region })
  const [asin, setAsin] = useState('')
  useEffect(() => { if (catalog.length && !catalog.find((c) => c.asin === asin)) setAsin(catalog[0].asin) }, [catalog]) // eslint-disable-line
  const { rows: raw, loading: rl, error: re } = useRows('asin_month', asin ? { region, asin } : { region, asin: '__none__' })
  const months = useMemo(() => [...new Set(raw.map((r) => r.month))].sort(), [raw])
  const mr = useMonthRange(months)
  const rows = useMemo(() => [...raw].filter((r) => mr.inRange(r.month)).sort((a, b) => a.month.localeCompare(b.month)), [raw, mr.from, mr.to])
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
        <MonthRange r={mr} />
      </div>
      <div className="kpis" style={{ marginBottom: 16 }}>
        <div className="kpi"><div className="v">{rl ? '…' : num(total)}</div><div className="l">Purchases (range, core)</div></div>
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
  const { sorted, sort, toggle } = useSort(rows, { col: null, dir: 'desc' })
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
            <thead><tr>
              <Th col="search_query" sort={sort} toggle={toggle}>Keyword</Th>
              <Th col="top_category" sort={sort} toggle={toggle}>Category</Th>
              <Th col="latest_volume" sort={sort} toggle={toggle} num>Volume/mo</Th>
              <Th col="our_purchase_share" sort={sort} toggle={toggle} num>Our share</Th>
              <Th col="our_purchases_12mo" sort={sort} toggle={toggle} num>Our purch (12mo)</Th>
              <Th col="trend" sort={sort} toggle={toggle}>Trend</Th></tr></thead>
            <tbody>{sorted.map((r) => (
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
  const months = useMemo(() => [...new Set(niche.filter((r) => r.family === family).map((r) => r.month))].sort(), [niche, family])
  const mr = useMonthRange(months)
  const series = useMemo(() => niche.filter((r) => r.family === family && mr.inRange(r.month)).sort((a, b) => a.month.localeCompare(b.month)), [niche, family, mr.from, mr.to])
  const last = series[series.length - 1] || {}
  const our12 = series.reduce((s, r) => s + (r.our_purchases || 0), 0)
  const tkS = useSort(tk, { col: 'our_purchases_12mo', dir: 'desc' })
  const { keywords, stack } = useMemo(() => {
    const cr = comp.filter((r) => mr.inRange(r.month))
    const ms = [...new Set(cr.map((r) => r.month))].sort()
    const tot = {}; cr.forEach((r) => { tot[r.keyword] = (tot[r.keyword] || 0) + r.volume })
    let kws = Object.keys(tot).filter((k) => k !== 'Other').sort((a, b) => tot[b] - tot[a])
    if (tot['Other'] != null) kws.push('Other')
    const bm = Object.fromEntries(ms.map((m) => [m, { month: m }]))
    cr.forEach((r) => { bm[r.month][r.keyword] = r.volume })
    return { keywords: kws, stack: ms.map((m) => bm[m]) }
  }, [comp, mr.from, mr.to])
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
        <MonthRange r={mr} />
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
        {tl ? <SkelRows n={8} /> : !tkS.sorted.length ? <Empty /> : (
          <div className="table-scroll"><table>
            <thead><tr>
              <Th col="search_query" sort={tkS.sort} toggle={tkS.toggle}>Keyword</Th>
              <Th col="latest_volume" sort={tkS.sort} toggle={tkS.toggle} num>Volume/mo</Th>
              <Th col="our_purchase_share" sort={tkS.sort} toggle={tkS.toggle} num>Our share</Th>
              <Th col="our_purchases_12mo" sort={tkS.sort} toggle={tkS.toggle} num>Our purch (12mo)</Th>
              <Th col="trend" sort={tkS.sort} toggle={tkS.toggle}>Trend</Th>
            </tr></thead>
            <tbody>{tkS.sorted.map((r) => (
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
  const { rows: fam, loading, error } = useRows('v_ad_family_month', { region: 'CA' })
  const [prog, setProg] = useState('All')
  const months = useMemo(() => [...new Set(fam.map((r) => r.month))].sort(), [fam])
  const mr = useMonthRange(months)
  const fr = useMemo(() => fam.filter((r) => (prog === 'All' || r.program === prog) && mr.inRange(r.month)), [fam, prog, mr.from, mr.to])
  const families = useMemo(() => [...new Set(fr.filter((r) => r.family).map((r) => r.family))].sort(), [fr])
  const [family, setFamily] = useState('')
  useEffect(() => { if (families.length && !families.includes(family)) setFamily(families[0]) }, [families]) // eslint-disable-line
  const scope = useMemo(() => fr.filter((r) => r.family === family), [fr, family])
  const series = useMemo(() => {
    const m = {}
    scope.forEach((r) => { const x = (m[r.month] = m[r.month] || { month: r.month, spend: 0, sales: 0 }); x.spend += r.spend || 0; x.sales += r.sales || 0 })
    return Object.values(m).sort((a, b) => a.month.localeCompare(b.month)).map((x) => ({ ...x, acos: x.sales ? x.spend / x.sales : null }))
  }, [scope])
  const famTable = useMemo(() => {
    const m = {}
    fr.forEach((r) => { if (!r.family) return; const x = (m[r.family] = m[r.family] || { family: r.family, spend: 0, sales: 0, clicks: 0, orders: 0 }); x.spend += r.spend || 0; x.sales += r.sales || 0; x.clicks += r.clicks || 0; x.orders += r.orders || 0 })
    return Object.values(m).map((x) => ({ ...x, acos: x.sales ? x.spend / x.sales : null }))
  }, [fr])
  const famS = useSort(famTable, { col: 'spend', dir: 'desc' })
  const tot = scope.reduce((s, r) => ({ spend: s.spend + (r.spend || 0), sales: s.sales + (r.sales || 0), orders: s.orders + (r.orders || 0) }), { spend: 0, sales: 0, orders: 0 })

  // deep-dive: keyword (search-term) level for the selected family
  const { rows: terms, loading: tl } = useRows('v_ad_term_enriched', family ? { region: 'CA', family } : { region: 'CA', family: '__none__' })
  const kf = useKwFilter()
  const kwAgg = useMemo(() => {
    const m = {}
    terms.filter((r) => (prog === 'All' || r.program === prog) && mr.inRange(r.month) && kf.pred(r.keyword)).forEach((r) => {
      const x = (m[r.keyword] = m[r.keyword] || { keyword: r.keyword, spend: 0, sales: 0, ad_clicks: 0, orders: 0, sqp_volume: null, clicks_l4w: null, impr_share: null, click_share: null, purch_share: null })
      x.spend += r.spend || 0; x.sales += r.sales || 0; x.ad_clicks += r.clicks || 0; x.orders += r.orders || 0
      x.sqp_volume = maxN(x.sqp_volume, r.sqp_volume); x.clicks_l4w = maxN(x.clicks_l4w, r.clicks_l4w)
      x.impr_share = maxN(x.impr_share, r.our_impr_share); x.click_share = maxN(x.click_share, r.our_click_share); x.purch_share = maxN(x.purch_share, r.our_purchase_share)
    })
    return Object.values(m).map((x) => ({ ...x, acos: x.sales ? x.spend / x.sales : null }))
  }, [terms, prog, mr.from, mr.to, kf.contains, kf.sel]) // eslint-disable-line
  const allKw = useMemo(() => [...new Set(terms.map((r) => r.keyword))].sort(), [terms])
  const { sorted: kwSorted, sort: kwSort, toggle: kwToggle } = useSort(kwAgg, { col: 'spend', dir: 'desc' })

  if (error) return <ErrorBanner msg={error} />
  return (
    <div>
      <div className="controls">
        <div className="field"><label htmlFor="ad-prog">Program</label>
          <select id="ad-prog" value={prog} onChange={(e) => setProg(e.target.value)}>
            <option value="All">All programs</option><option value="SP">Sponsored Products</option><option value="SB">Sponsored Brands</option>
          </select></div>
        <div className="field"><label htmlFor="ad-fam">Family</label>
          <select id="ad-fam" value={family} onChange={(e) => setFamily(e.target.value)}>{families.map((f) => <option key={f}>{f}</option>)}</select></div>
        <MonthRange r={mr} />
        <span className="muted small" style={{ alignSelf: 'flex-end' }}>Canada · Vendor Central ads</span>
      </div>
      <div className="kpis" style={{ marginBottom: 16 }}>
        <div className="kpi"><div className="v">{loading ? '…' : money(tot.spend, 'CA')}</div><div className="l">Ad spend · {family}</div></div>
        <div className="kpi"><div className="v">{loading ? '…' : money(tot.sales, 'CA')}</div><div className="l">Ad sales</div></div>
        <div className="kpi"><div className="v">{loading ? '…' : (tot.sales ? (tot.spend / tot.sales * 100).toFixed(0) + '%' : '—')}</div><div className="l">ACOS</div></div>
        <div className="kpi"><div className="v">{loading ? '…' : num(tot.orders)}</div><div className="l">Ad orders</div></div>
      </div>
      <div className="card"><h3>Spend &amp; ACOS over time · {family}</h3>
        {loading ? <SkelChart /> : !series.length ? <Empty /> : (
          <ResponsiveContainer width="100%" height={240}><LineChart data={series} margin={{ left: -6 }}>
            <CartesianGrid stroke={C.grid} strokeDasharray="3 3" /><XAxis dataKey="month" tick={axisTick} />
            <YAxis yAxisId="s" tick={axisTick} tickFormatter={kfmt} /><YAxis yAxisId="a" orientation="right" tick={axisTick} tickFormatter={(v) => (v * 100).toFixed(0) + '%'} />
            <Tooltip contentStyle={tipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
            <Line yAxisId="s" dataKey="spend" stroke={C.violet} strokeWidth={2} dot={false} name="Spend" isAnimationActive={!REDUCED} />
            <Line yAxisId="a" dataKey="acos" stroke={C.warn} dot={false} name="ACOS" isAnimationActive={!REDUCED} />
          </LineChart></ResponsiveContainer>)}
      </div>
      <div className="card"><h3>Families by ad spend <span className="muted small">· click a row to deep-dive</span></h3>
        {loading ? <SkelRows n={8} /> : !famS.sorted.length ? <Empty /> : (
          <div className="table-scroll"><table>
            <thead><tr>
              <Th col="family" sort={famS.sort} toggle={famS.toggle}>Family</Th>
              <Th col="spend" sort={famS.sort} toggle={famS.toggle} num>Spend</Th>
              <Th col="sales" sort={famS.sort} toggle={famS.toggle} num>Sales</Th>
              <Th col="acos" sort={famS.sort} toggle={famS.toggle} num>ACOS</Th>
              <Th col="orders" sort={famS.sort} toggle={famS.toggle} num>Orders</Th>
            </tr></thead>
            <tbody>{famS.sorted.map((r) => (
              <tr key={r.family} className="rowbtn" style={{ background: r.family === family ? 'var(--panel2)' : undefined }} onClick={() => setFamily(r.family)}>
                <td><b>{r.family}</b></td><td className="num">{money(r.spend, 'CA')}</td>
                <td className="num">{money(r.sales, 'CA')}</td>
                <td className="num"><span className={'badge ' + (r.acos > 0.25 ? 'down' : r.acos ? 'up' : 'flat')}>{r.acos ? (r.acos * 100).toFixed(0) + '%' : '—'}</span></td>
                <td className="num">{num(r.orders)}</td></tr>))}
            </tbody></table></div>)}
      </div>
      <div className="card"><h3>Keywords driving {family} <span className="muted small">({kwSorted.length})</span></h3>
        <div className="controls" style={{ marginBottom: 12 }}><KwFilter all={allKw} f={kf} /></div>
        {tl ? <SkelRows n={10} /> : !kwSorted.length ? <Empty msg={kf.active ? 'No keywords match the filter.' : 'No ad search terms for this family in range.'} /> : (
          <div className="table-scroll"><table>
            <thead><tr>
              <Th col="keyword" sort={kwSort} toggle={kwToggle}>Keyword (search term)</Th>
              <Th col="spend" sort={kwSort} toggle={kwToggle} num>Spend</Th>
              <Th col="sales" sort={kwSort} toggle={kwToggle} num>Sales</Th>
              <Th col="acos" sort={kwSort} toggle={kwToggle} num>ACOS</Th>
              <Th col="orders" sort={kwSort} toggle={kwToggle} num>Orders</Th>
              <Th col="sqp_volume" sort={kwSort} toggle={kwToggle} num>SQP vol/mo</Th>
              <Th col="clicks_l4w" sort={kwSort} toggle={kwToggle} num>Clicks L4W</Th>
              <Th col="impr_share" sort={kwSort} toggle={kwToggle} num>Impr %</Th>
              <Th col="click_share" sort={kwSort} toggle={kwToggle} num>Click %</Th>
              <Th col="purch_share" sort={kwSort} toggle={kwToggle} num>Purch %</Th>
            </tr></thead>
            <tbody>{kwSorted.slice(0, 400).map((r) => (
              <tr key={r.keyword}>
                <td><b>{r.keyword}</b></td>
                <td className="num">{money(r.spend, 'CA')}</td>
                <td className="num">{money(r.sales, 'CA')}</td>
                <td className="num"><span className={'badge ' + (r.acos > 0.25 ? 'down' : r.acos ? 'up' : 'flat')}>{r.acos ? (r.acos * 100).toFixed(0) + '%' : '—'}</span></td>
                <td className="num muted">{num(r.orders)}</td>
                <td className="num">{r.sqp_volume == null ? '-' : num(r.sqp_volume)}</td>
                <td className="num">{r.clicks_l4w == null ? '-' : num(r.clicks_l4w)}</td>
                <td className="num">{r.impr_share == null ? '-' : pct(r.impr_share)}</td>
                <td className="num">{r.click_share == null ? '-' : pct(r.click_share)}</td>
                <td className="num">{r.purch_share == null ? '-' : pct(r.purch_share)}</td>
              </tr>))}
            </tbody></table></div>)}
        <div className="muted small" style={{ marginTop: 8 }}>Spend / Sales / Orders = ad totals over the selected months. <b>SQP vol</b>, <b>Clicks L4W</b> and <b>Impr / Click / Purch %</b> are the latest-month organic &amp; market signals for that search term (“-” if not in SQP / Datarova). Click any column to sort. Showing up to 400.</div>
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
  const families = useMemo(() => [...new Set(rows.map((r) => r.manual_family || r.auto_family).filter((x) => x && x !== 'Brand Level'))].sort(), [rows])
  const effOf = (r) => r.manual_family || r.auto_family
  const filtered = useMemo(() => rows.filter((r) => {
    const eff = effOf(r); const isBrand = eff === 'Brand Level'
    const need = statusF === 'all' ? true
      : statusF === 'mapped' ? (!!eff && !isBrand)
      : statusF === 'brand' ? isBrand
      : !eff  // 'needs'
    const txt = !q || (r.campaign_name || '').toLowerCase().includes(q.toLowerCase())
    return need && txt
  }), [rows, statusF, q])
  const { sorted, sort, toggle } = useSort(filtered, { col: 'spend', dir: 'desc' })
  const save = async (row, val) => {
    const { error } = await supabase.from('campaign_map').update({ manual_family: val })
      .eq('program', row.program).eq('campaign_id', row.campaign_id)
    if (error) { setErr(error.message); if (isAuthErr(error)) supabase.auth.signOut(); return }
    setRows((rs) => rs.map((r) => (r.program === row.program && r.campaign_id === row.campaign_id ? { ...r, manual_family: val } : r)))
    setSaved(row.campaign_id + ''); setTimeout(() => setSaved(''), 1200)
  }
  const needCount = rows.filter((r) => !effOf(r)).length
  const brandCount = rows.filter((r) => effOf(r) === 'Brand Level').length
  return (
    <div>
      <div className="controls">
        <div className="field" style={{ flex: 1, minWidth: 220 }}><label htmlFor="cm-q">Search campaign</label>
          <input id="cm-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="campaign name…" /></div>
        <div className="field"><label htmlFor="cm-f">Show</label>
          <select id="cm-f" value={statusF} onChange={(e) => setStatusF(e.target.value)}>
            <option value="needs">Needs mapping ({needCount})</option>
            <option value="mapped">Mapped to a family</option>
            <option value="brand">Brand Level ({brandCount})</option>
            <option value="all">All</option>
          </select></div>
      </div>
      <div className="card">
        <h3>Campaign → Family mapping · Canada {saved && <span className="badge up">saved ✓</span>}</h3>
        {err && <ErrorBanner msg={err} onRetry={load} />}
        {loading ? <SkelRows n={10} /> : !sorted.length ? <Empty msg="Nothing here." /> : (
          <div className="table-scroll"><table>
            <thead><tr>
              <Th col="campaign_name" sort={sort} toggle={toggle}>Campaign</Th>
              <Th col="program" sort={sort} toggle={toggle}>Prog</Th>
              <Th col="spend" sort={sort} toggle={toggle} num>Spend</Th>
              <Th col="asin" sort={sort} toggle={toggle}>ASIN</Th>
              <Th col="auto_family" sort={sort} toggle={toggle}>Auto family</Th>
              <th>Map to</th>
            </tr></thead>
            <tbody>{sorted.slice(0, 300).map((r) => {
              const eff = effOf(r)
              return (
                <tr key={r.program + r.campaign_id}>
                  <td style={{ maxWidth: 320 }}><span className="small">{r.campaign_name}</span></td>
                  <td className="small muted">{r.program}</td>
                  <td className="num">{money(r.spend, 'CA')}</td>
                  <td className="small muted">{r.asin || '—'}</td>
                  <td className="small">{r.auto_family === 'Brand Level' ? <span className="badge flat">Brand Level</span> : r.auto_family || <span className="badge down">none</span>}</td>
                  <td>
                    <select value={r.manual_family || ''} onChange={(e) => save(r, e.target.value)}
                            style={{ minHeight: 34, borderColor: eff ? 'var(--line)' : 'var(--hot)' }}>
                      <option value="">{r.auto_family ? `(use auto: ${r.auto_family})` : '— set —'}</option>
                      <option value="Brand Level">Brand Level</option>
                      {families.map((f) => <option key={f} value={f}>{f}</option>)}
                    </select>
                  </td>
                </tr>)
            })}</tbody></table></div>)}
        <div className="muted small" style={{ marginTop: 10 }}>Edits save instantly and the Ads views re-aggregate live. <b>Brand Level</b> = umbrella / brand campaigns that shouldn’t roll into one family (pick it for any campaign, e.g. “[Brand] All Products”). {needCount} need mapping · {brandCount} brand-level. Click a header to sort. Showing up to 300.</div>
      </div>
    </div>
  )
}

/* ---------------- Organic Ranks (by family) ---------------- */
const rankBadge = (t) => 'badge ' + (t === 'Improving' || t === 'New' ? 'up' : t === 'Declining' || t === 'Lost' ? 'down' : 'flat')
const rk = (v) => (v == null ? '—' : '#' + (Number.isInteger(v) ? v : v.toFixed(0)))
function OrganicRanks({ region }) {
  const { rows: days, loading: dl, error: de } = useRows('rank_family_day', { region })
  const families = useMemo(() => [...new Set(days.map((r) => r.family))].sort(), [days])
  const [family, setFamily] = useState('')
  useEffect(() => { if (families.length && !families.includes(family)) setFamily(families[0]) }, [families]) // eslint-disable-line
  const { rows: kws, loading: kl } = useRows('v_rank_kw_enriched', family ? { region, family } : { region, family: '__none__' })
  const allDates = useMemo(() => [...new Set(days.filter((r) => r.family === family).map((r) => r.date))].sort(), [days, family])
  const [from, setFrom] = useState(''); const [to, setTo] = useState('')
  useEffect(() => { if (allDates.length) { setFrom(allDates[0]); setTo(allDates[allDates.length - 1]) } }, [family, allDates.length]) // eslint-disable-line
  const series = useMemo(() => days.filter((r) => r.family === family && (!from || r.date >= from) && (!to || r.date <= to))
    .sort((a, b) => a.date.localeCompare(b.date)), [days, family, from, to])
  const last = series[series.length - 1] || {}
  const kf = useKwFilter()
  const allKw = useMemo(() => [...new Set(kws.map((r) => r.keyword))].sort(), [kws])
  const filtered = useMemo(() => kws.filter((r) => kf.pred(r.keyword)), [kws, kf.contains, kf.sel]) // eslint-disable-line
  const { sorted, sort, toggle } = useSort(filtered, { col: 'latest_rank', dir: 'asc' })
  if (de) return <ErrorBanner msg={de} />
  return (
    <div>
      <div className="controls">
        <div className="field"><label htmlFor="rk-fam">Family</label>
          <select id="rk-fam" value={family} onChange={(e) => setFamily(e.target.value)} disabled={dl}>
            {families.map((fam) => <option key={fam}>{fam}</option>)}</select></div>
        <div className="field"><label htmlFor="rk-from">From</label>
          <select id="rk-from" value={from} onChange={(e) => setFrom(e.target.value)}>{allDates.map((d) => <option key={d}>{d}</option>)}</select></div>
        <div className="field"><label htmlFor="rk-to">To</label>
          <select id="rk-to" value={to} onChange={(e) => setTo(e.target.value)}>{allDates.map((d) => <option key={d}>{d}</option>)}</select></div>
        <span className="muted small" style={{ alignSelf: 'flex-end' }}>organic rank · lower = better</span>
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
        <h3>Keywords · {family} <span className="muted small">({sorted.length})</span></h3>
        <div className="controls" style={{ marginBottom: 12 }}><KwFilter all={allKw} f={kf} /></div>
        {kl ? <SkelRows n={10} /> : !sorted.length ? <Empty msg={kf.active ? 'No keywords match the filter.' : undefined} /> : (
          <div className="table-scroll"><table>
            <thead><tr>
              <Th col="keyword" sort={sort} toggle={toggle}>Keyword</Th>
              <Th col="latest_rank" sort={sort} toggle={toggle} num>Now</Th>
              <Th col="best_rank" sort={sort} toggle={toggle} num>Best</Th>
              <Th col="avg_rank" sort={sort} toggle={toggle} num>Avg</Th>
              <Th col="sqp_volume" sort={sort} toggle={toggle} num>SQP vol/mo</Th>
              <Th col="clicks_l4w" sort={sort} toggle={toggle} num>Clicks L4W</Th>
              <Th col="days_ranked" sort={sort} toggle={toggle} num>Ranked days</Th>
              <Th col="ac_badge" sort={sort} toggle={toggle}>AC</Th>
              <Th col="trend" sort={sort} toggle={toggle}>Trend</Th>
            </tr></thead>
            <tbody>{sorted.slice(0, 400).map((r) => (
              <tr key={r.keyword}>
                <td><b>{r.keyword}</b></td>
                <td className="num">{rk(r.latest_rank)}</td>
                <td className="num">{rk(r.best_rank)}</td>
                <td className="num muted">{r.avg_rank == null ? '—' : r.avg_rank}</td>
                <td className="num">{r.sqp_volume == null ? '-' : num(r.sqp_volume)}</td>
                <td className="num">{r.clicks_l4w == null ? '-' : num(r.clicks_l4w)}</td>
                <td className="num muted">{r.days_ranked}/{r.days_tracked}</td>
                <td>{r.ac_badge ? <span className="badge up">AC</span> : ''}</td>
                <td><span className={rankBadge(r.trend)}>{r.trend}</span></td>
              </tr>))}
            </tbody></table></div>)}
        <div className="muted small" style={{ marginTop: 8 }}>“Now” = latest organic position (lower is better); blank = not ranked. <b>SQP vol/mo</b> = latest-month search volume (“-” if not in SQP). <b>Clicks L4W</b> = market keyword clicks last 4 weeks (Datarova). Click any column header to sort. Showing up to 400.</div>
      </div>
    </div>
  )
}

/* ---------------- Catalog (editable ASIN → family / SKU / category) ---------------- */
function CatalogTab() {
  const [rows, setRows] = useState([]); const [loading, setLoading] = useState(true); const [err, setErr] = useState(null)
  const [regionF, setRegionF] = useState('All'); const [q, setQ] = useState(''); const [saved, setSaved] = useState('')
  const blank = { region: 'CA', asin: '', family: '', category: '', sku: '', model: '', brand: '' }
  const [adding, setAdding] = useState(blank)
  const load = () => { setLoading(true); fetchAll('catalog')
    .then((d) => { setRows(d); setLoading(false) }).catch((e) => { setErr(e.message); setLoading(false) }) }
  useEffect(load, [])
  const families = useMemo(() => [...new Set(rows.map((r) => r.family).filter(Boolean))].sort(), [rows])
  const categories = useMemo(() => [...new Set(rows.map((r) => r.category).filter(Boolean))].sort(), [rows])
  const filtered = useMemo(() => rows.filter((r) => {
    const okR = regionF === 'All' || r.region === regionF
    const t = q.toLowerCase()
    const okQ = !q || [r.asin, r.family, r.category, r.sku, r.model, r.brand].some((v) => (v || '').toLowerCase().includes(t))
    return okR && okQ
  }), [rows, regionF, q])
  const { sorted, sort, toggle } = useSort(filtered, { col: 'family', dir: 'asc' })

  const flash = (id) => { setSaved(id); setTimeout(() => setSaved(''), 1400) }
  const saveCell = async (row, field, value) => {
    value = value.trim(); if ((row[field] || '') === value) return
    const { error } = await supabase.from('catalog').update({ [field]: value || null }).eq('region', row.region).eq('asin', row.asin)
    if (error) { setErr(error.message); if (isAuthErr(error)) supabase.auth.signOut(); return }
    setRows((rs) => rs.map((r) => (r.region === row.region && r.asin === row.asin ? { ...r, [field]: value } : r))); flash(row.region + row.asin)
  }
  const addRow = async () => {
    const a = adding; const asin = a.asin.trim().toUpperCase()
    if (!asin) { setErr('ASIN is required.'); return }
    if (rows.find((r) => r.region === a.region && r.asin === asin)) { setErr(`${asin} already exists in ${a.region}.`); return }
    const rec = { region: a.region, asin, family: a.family || null, category: a.category || null, sku: a.sku || null, model: a.model || null, brand: a.brand || null }
    const { error } = await supabase.from('catalog').insert(rec)
    if (error) { setErr(error.message); if (isAuthErr(error)) supabase.auth.signOut(); return }
    setErr(null); setRows((rs) => [...rs, rec]); setAdding({ ...blank, region: a.region }); flash('added')
  }
  const delRow = async (row) => {
    if (!window.confirm(`Remove ${row.asin} (${row.region}) from the catalog?`)) return
    const { error } = await supabase.from('catalog').delete().eq('region', row.region).eq('asin', row.asin)
    if (error) { setErr(error.message); return }
    setRows((rs) => rs.filter((r) => !(r.region === row.region && r.asin === row.asin)))
  }
  return (
    <div>
      <datalist id="cat-fams">{families.map((f) => <option key={f} value={f} />)}</datalist>
      <datalist id="cat-cats">{categories.map((c) => <option key={c} value={c} />)}</datalist>
      <div className="controls">
        <div className="field"><label htmlFor="cat-reg">Region</label>
          <select id="cat-reg" value={regionF} onChange={(e) => setRegionF(e.target.value)}><option>All</option><option>US</option><option>CA</option></select></div>
        <div className="field" style={{ flex: 1, minWidth: 220 }}><label htmlFor="cat-q">Search</label>
          <input id="cat-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="ASIN, family, category, SKU…" /></div>
      </div>
      <div className="card">
        <h3>Add an ASIN {saved === 'added' && <span className="badge up">added ✓</span>}</h3>
        <div className="controls" style={{ alignItems: 'flex-end', marginBottom: 0 }}>
          <div className="field"><label>Region</label><select value={adding.region} onChange={(e) => setAdding({ ...adding, region: e.target.value })}><option>CA</option><option>US</option></select></div>
          <div className="field"><label>ASIN *</label><input value={adding.asin} onChange={(e) => setAdding({ ...adding, asin: e.target.value })} placeholder="B0…" style={{ width: 128 }} /></div>
          <div className="field"><label>Family</label><input list="cat-fams" value={adding.family} onChange={(e) => setAdding({ ...adding, family: e.target.value })} placeholder="pick or type" /></div>
          <div className="field"><label>Category</label><input list="cat-cats" value={adding.category} onChange={(e) => setAdding({ ...adding, category: e.target.value })} placeholder="pick or type" /></div>
          <div className="field"><label>SKU</label><input value={adding.sku} onChange={(e) => setAdding({ ...adding, sku: e.target.value })} style={{ width: 130 }} /></div>
          <div className="field"><label>Product / Model</label><input value={adding.model} onChange={(e) => setAdding({ ...adding, model: e.target.value })} /></div>
          <button className="primary" onClick={addRow}>Add ASIN</button>
        </div>
      </div>
      <div className="card">
        <h3>Catalog — ASIN → family / SKU / category <span className="muted small">({sorted.length})</span> {saved && saved !== 'added' && <span className="badge up">saved ✓</span>}</h3>
        {err && <ErrorBanner msg={err} onRetry={load} />}
        {loading ? <SkelRows n={10} /> : !sorted.length ? <Empty /> : (
          <div className="table-scroll"><table>
            <thead><tr>
              <Th col="asin" sort={sort} toggle={toggle}>ASIN</Th>
              <Th col="region" sort={sort} toggle={toggle}>Region</Th>
              <Th col="family" sort={sort} toggle={toggle}>Family</Th>
              <Th col="category" sort={sort} toggle={toggle}>Category</Th>
              <Th col="sku" sort={sort} toggle={toggle}>SKU</Th>
              <Th col="model" sort={sort} toggle={toggle}>Product / Model</Th>
              <th aria-label="remove" />
            </tr></thead>
            <tbody>{sorted.slice(0, 500).map((r) => (
              <tr key={r.region + r.asin}>
                <td className="small"><b>{r.asin}</b></td>
                <td className="small muted">{r.region}</td>
                <td><input className="cell-input" list="cat-fams" defaultValue={r.family || ''} onBlur={(e) => saveCell(r, 'family', e.target.value)} /></td>
                <td><input className="cell-input" list="cat-cats" defaultValue={r.category || ''} onBlur={(e) => saveCell(r, 'category', e.target.value)} /></td>
                <td><input className="cell-input" defaultValue={r.sku || ''} onBlur={(e) => saveCell(r, 'sku', e.target.value)} /></td>
                <td><input className="cell-input" defaultValue={r.model || ''} onBlur={(e) => saveCell(r, 'model', e.target.value)} /></td>
                <td><button className="ghost small" title="remove" onClick={() => delRow(r)}>✕</button></td>
              </tr>))}
            </tbody></table></div>)}
        <div className="muted small" style={{ marginTop: 10 }}>Edits save when you leave a cell. Family / Category accept an existing value (dropdown) or a new one you type. New ASINs flow into Family, Categories, ASIN Explorer and auto-map ad campaigns on the next refresh. Showing up to 500.</div>
      </div>
    </div>
  )
}

/* ---------------- App shell ---------------- */
export default function App() {
  const [authed, setAuthed] = useState(false); const [ready, setReady] = useState(false)
  const [tab, setTab] = useState('dash'); const [region, setRegion] = useState('US')
  const [dataRange, setDataRange] = useState('')
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => { setAuthed(!!data.session); setReady(true) })
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => setAuthed(!!session))
    return () => sub.subscription.unsubscribe()
  }, [])
  useEffect(() => {
    if (!authed) return
    ;(async () => {
      const lo = await supabase.from('category_month').select('month').order('month', { ascending: true }).limit(1)
      const hi = await supabase.from('category_month').select('month').order('month', { ascending: false }).limit(1)
      const a = lo.data?.[0]?.month, b = hi.data?.[0]?.month
      if (a && b) setDataRange(`${fmtMonth(a)}–${fmtMonth(b)}`)
    })().catch(() => {})
  }, [authed])
  if (!ready) return <div className="app"><SkelRows n={4} /></div>
  if (!authed) return <Login onIn={() => setAuthed(true)} />
  const TABS = [['dash', 'Dashboard'], ['keyword', 'Keyword Explorer'], ['family', 'Family Explorer'], ['ranks', 'Organic Ranks'], ['ads', 'Ads'], ['map', 'Campaign Map'], ['cats', 'Categories'], ['asin', 'ASIN Explorer'], ['catalog', 'Catalog'], ['dl', 'Downloads']]
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
    catalog: SI('M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2zM4 5v14M9 3v16'),
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
        {tab === 'ranks' && <OrganicRanks region={region} />}
        {tab === 'ads' && <AdsExplorer />}
        {tab === 'map' && <CampaignMapping />}
        {tab === 'cats' && <Categories region={region} />}
        {tab === 'asin' && <AsinExplorer region={region} />}
        {tab === 'catalog' && <CatalogTab />}
        {tab === 'dl' && <Downloads region={region} />}
        <div className="muted small" style={{ marginTop: 20 }}>
          Data: Amazon Brand Analytics SQP · {dataRange || '…'} · search-attributed purchases (not total units; excludes 1P/Vendor).
        </div>
      </main>
    </div>
  )
}
