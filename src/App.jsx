import { useEffect, useMemo, useState } from 'react';
import { Link, NavLink, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useOutletContext } from 'react-router-dom';
import { ArrowRight, Bell, Check, CheckCircle2, ChevronDown, House, Leaf, Menu, Plus, ShieldCheck, Sparkles, Users, X, MessageCircle, ClipboardCheck, Coins } from 'lucide-react';
import Mascot from './components/Mascot.jsx';
import { api, setHouseholdSession } from './api.js';
import { AskPage, BillsPage, ChoresPage, HouseBoardPage, HouseRulesPage, NotFound } from './pages/FeaturePages.jsx';

const NAV_ITEMS = [
  { to: '/home', label: 'Home', icon: House, end: true },
  { to: '/rules', label: 'House Rules', icon: ShieldCheck },
  { to: '/board', label: 'House Board', icon: MessageCircle },
  { to: '/ask', label: 'Ask homi.', icon: Sparkles },
  { to: '/chores', label: 'Chores', icon: ClipboardCheck },
  { to: '/bills', label: 'Bills & Rent', icon: Coins },
];

function Brand({ compact = false }) {
  return <Link className={`brand ${compact ? 'brand--compact' : ''}`} to="/" aria-label="homi. home"><span className="brand-mark"><House size={19} strokeWidth={2.5} /></span><span>homi<span className="brand-dot">.</span></span></Link>;
}

function Welcome() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function tryDemo() {
    setBusy(true); setError('');
    try {
      const household = await api('/api/households/demo');
      setHouseholdSession(household, household.members[0]?.id);
      navigate('/home');
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <main className="welcome-page">
    <header className="welcome-header wrap"><Brand /><span className="welcome-header-note"><span className="online-dot" /> Your little corner of calm</span></header>
    <section className="welcome-hero wrap">
      <div className="welcome-copy"><span className="eyebrow"><Leaf size={14} /> A happier home starts here</span><h1>Living together,<br /><span>a little easier.</span></h1><p className="welcome-lede">A thoughtful home for the little things that make shared living feel good.</p><p className="welcome-supporting">The Roomie That Never Takes Sides.</p>
        <div className="welcome-buttons"><button className="button button--primary button--large" onClick={tryDemo} disabled={busy}>{busy ? 'Opening your home…' : 'Try the demo'} <ArrowRight size={17} /></button><button className="button button--light button--large" onClick={() => navigate('/create')}>Create a household</button></div>
        {error && <p className="form-error" role="alert">{error}</p>}<p className="privacy-note"><Check size={14} /> No sign-up needed to look around</p>
      </div>
      <div className="welcome-art"><div className="art-sun" /><div className="welcome-note note-top"><span className="note-icon note-icon--yellow"><Sparkles size={15} /></span><span><strong>A little more understood</strong><small>Room for everyone to feel at home</small></span></div><div className="mascot-stage"><Mascot size="hero" /><span className="mascot-name">Little Homi</span></div><div className="welcome-note note-bottom"><span className="note-icon note-icon--green"><CheckCircle2 size={15} /></span><span><strong>Same team, same home</strong><small>Thoughtful help when you need it</small></span></div><span className="art-sparkle sparkle-one">✳</span><span className="art-sparkle sparkle-two">✦</span></div>
    </section>
    <section className="welcome-foot wrap"><span>Made for the people you come home to.</span><span className="welcome-foot-tagline">Better Living. Less Drama.</span></section>
  </main>;
}

function CreateHousehold() {
  const navigate = useNavigate();
  const [houseName, setHouseName] = useState('');
  const [names, setNames] = useState(['']);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault();
    const cleaned = names.map((name) => name.trim()).filter(Boolean);
    if (!cleaned.length) { setError('Add your name so your roommates know who started the home.'); return; }
    setBusy(true); setError('');
    try {
      const household = await api('/api/households', { method: 'POST', body: JSON.stringify({ name: houseName.trim(), members: cleaned }) });
      setHouseholdSession(household, household.members[0]?.id);
      navigate('/home');
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <main className="create-page"><header className="welcome-header wrap"><Brand /><Link to="/" className="back-link">Back to welcome</Link></header>
    <section className="create-card"><div className="create-mascot"><Mascot size="small" /></div><span className="eyebrow">Let's make room for everyone</span><h1>Start your household</h1><p className="muted">A few details and you’ll be right at home.</p>
      <form onSubmit={submit} className="create-form"><label className="field-label" htmlFor="house-name">What do you call your place?</label><input id="house-name" value={houseName} onChange={(event) => setHouseName(event.target.value)} placeholder="e.g. Willow House" minLength={2} maxLength={60} required />
        <div className="roommate-label-row"><label className="field-label" htmlFor="roommate-0">Who lives there?</label><span className="field-hint">Up to 8 people</span></div>
        <div className="roommate-inputs">{names.map((name, index) => <div className="roommate-input" key={index}><span className="mini-avatar" aria-hidden="true">{name.trim().charAt(0).toUpperCase() || (index === 0 ? 'Y' : '＋')}</span><input id={`roommate-${index}`} value={name} onChange={(event) => setNames((items) => items.map((item, i) => i === index ? event.target.value : item))} placeholder={index === 0 ? 'Your name' : 'Roommate name'} maxLength={50} aria-label={index === 0 ? 'Your name' : `Roommate ${index} name`} /></div>)}</div>
        {names.length < 8 && <button type="button" className="text-button add-roommate" onClick={() => setNames((items) => [...items, ''])}><Plus size={15} /> Add a roommate</button>}
        {error && <p className="form-error" role="alert">{error}</p>}<button className="button button--primary button--full" type="submit" disabled={busy}>{busy ? 'Making your home…' : 'Create my household'} <ArrowRight size={17} /></button>
      </form><p className="form-footnote"><ShieldCheck size={14} /> This demo saves your household on this device.</p>
    </section>
  </main>;
}

function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [household, setHousehold] = useState(null);
  const [activeMemberId, setActiveMemberId] = useState(localStorage.getItem('homi:memberId') || '');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const householdId = localStorage.getItem('homi:householdId');
  async function refreshHousehold(memberOverride = '') {
    if (!householdId) { setLoading(false); return; }
    try {
      const requestedMemberId = memberOverride || localStorage.getItem('homi:memberId') || '';
      const householdPath = householdId === 'willow-house-demo' ? '/api/households/demo' : `/api/households/${householdId}`;
      const memberQuery = requestedMemberId ? `?member_id=${encodeURIComponent(requestedMemberId)}` : '';
      const data = await api(`${householdPath}${memberQuery}`);
      setHousehold(data);
      const saved = localStorage.getItem('homi:memberId');
      const memberId = data.members.find((member) => member.id === saved)?.id || data.members[0]?.id || '';
      setActiveMemberId(memberId); localStorage.setItem('homi:memberId', memberId); setError('');
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }
  useEffect(() => { refreshHousehold(); }, [householdId]);
  useEffect(() => { setNoticeOpen(false); setMobileNav(false); }, [location.pathname]);
  const activeMember = household?.members.find((member) => member.id === activeMemberId) || household?.members[0];
  const unreadCount = household?.notifications.filter((item) => !item.is_read).length || 0;
  const context = useMemo(() => ({ household, activeMember, setHousehold, refreshHousehold }), [household, activeMember]);
  if (!householdId) return <Navigate to="/" replace />;
  if (loading) return <div className="screen-loading"><Mascot size="small" /><span>Making yourself at home…</span></div>;
  if (error && !household) return <div className="screen-loading screen-loading--error"><p>{error}</p><button className="button button--light" onClick={() => navigate('/')}>Back to welcome</button></div>;
  return <div className="app-frame">
    <aside className={`sidebar ${mobileNav ? 'sidebar--open' : ''}`}><div className="sidebar-brand-row"><Brand compact /><button className="icon-button mobile-close" onClick={() => setMobileNav(false)} aria-label="Close navigation"><X size={19} /></button></div>
      <div className="home-label">YOUR HOME</div><nav className="sidebar-nav" aria-label="Main navigation">{NAV_ITEMS.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`}><Icon size={18} strokeWidth={1.8} /><span>{label}</span>{label === 'Ask homi.' && <span className="nav-new">AI</span>}</NavLink>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-mascot"><Mascot size="tiny" /><div><strong>Little Homi</strong><span>Here for your household</span></div></div><div className="sidebar-tagline">Better living, together.</div></div>
    </aside>
    {mobileNav && <button className="mobile-scrim" onClick={() => setMobileNav(false)} aria-label="Close navigation overlay" />}
    <div className="app-main"><header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={20} /></button><span className="household-crumb"><span className="crumb-home"><House size={14} /></span>{household.name}<ChevronDown size={14} /></span></div>
      <div className="topbar-right"><div className="notification-wrap"><button className={`icon-button notification-button ${noticeOpen ? 'icon-button--selected' : ''}`} aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ''}`} onClick={() => setNoticeOpen((value) => !value)}><Bell size={18} />{unreadCount > 0 && <span className="notification-dot" />}</button>
        {noticeOpen && <div className="notification-popover"><div className="popover-heading"><div><strong>Little updates</strong><span>Your home at a glance</span></div><span className="notice-count">{unreadCount} new</span></div>{household.notifications.slice(0, 8).map((item) => { const destination = item.entity_type === 'board_post' ? `/board?post=${encodeURIComponent(item.entity_id)}` : item.kind === 'chore' ? '/chores' : item.kind === 'rule' ? '/rules' : '/board'; return <Link className={`notification-item ${item.is_read ? 'notification-item--read' : ''}`} to={destination} key={item.id} onClick={() => { setNoticeOpen(false); if (!item.is_read) api(`/api/households/${household.id}/notifications/${item.id}/read`, { method: 'POST', body: JSON.stringify({ member_id: activeMemberId }) }).then(setHousehold).catch(() => {}); }}><span className={`notification-icon notification-icon--${item.kind}`}><Bell size={14} /></span><span className="notification-copy"><strong>{item.title}</strong><span>{item.detail}</span></span>{!item.is_read && <span className="notification-unread-dot" aria-label="Unread" />}</Link>; })}{!household.notifications.length && <p className="empty-notifications">Nothing new just yet.</p>}</div>}</div>
        <span className="topbar-divider" /><label className="profile-switcher"><span className={`avatar avatar--${activeMember?.color || 'sage'}`}>{activeMember?.name?.split(' ').map((part) => part[0]).slice(0, 2).join('')}</span><select aria-label="Switch roommate profile" value={activeMemberId} onChange={(event) => { const memberId = event.target.value; setActiveMemberId(memberId); localStorage.setItem('homi:memberId', memberId); refreshHousehold(memberId); }}><option value="" disabled>Your profile</option>{household.members.map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select><ChevronDown size={14} /></label></div></header>
      <main className="page-content"><Outlet context={context} /></main>
    </div>{error && <div className="toast-error" role="status">{error}</div>}
  </div>;
}

function useHome() { return useOutletContext(); }
function Avatar({ member, size = 'normal' }) {
  const initials = member.name.split(' ').map((part) => part[0]).slice(0, 2).join('');
  return <span className={`avatar avatar--${member.color || 'sage'} avatar--${size}`} aria-label={member.name}>{initials}</span>;
}
function SectionHeading({ eyebrow, title, to }) {
  return <div className="section-heading"><div><span className="eyebrow-small">{eyebrow}</span><h2>{title}</h2></div>{to && <Link className="subtle-link" to={to}>See all <ArrowRight size={14} /></Link>}</div>;
}
function getGreeting() { const hour = new Date().getHours(); return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'; }

function Dashboard() {
  const { household, activeMember, setHousehold } = useHome();
  const openChores = household.chores.filter((chore) => !chore.completed).slice(0, 3);
  const totalDue = household.expense_totals ? household.expense_totals.outstanding_cents / 100 : household.expenses.filter((expense) => expense.status !== 'Settled').reduce((sum, expense) => sum + Number(expense.amount), 0);
  async function toggleChore(chore) {
    try { setHousehold(await api(`/api/households/${household.id}/chores/${chore.id}?member_id=${encodeURIComponent(activeMember.id)}`, { method: 'PATCH', body: JSON.stringify({ completed: !chore.completed }) })); } catch { /* the dashboard remains usable if an update fails */ }
  }
  return <div className="dashboard page-enter">
    <section className="dashboard-hero">
      <div className="hero-text">
        <span className="eyebrow hero-eyebrow"><span className="online-dot" /> YOUR HOUSEHOLD, IN HARMONY</span>
        <h1>{getGreeting()},<br /><span>{activeMember?.name?.split(' ')[0] || 'roomie'}.</span></h1>
        <p>Welcome to <strong>{household.name}</strong>. A softer landing for the everyday stuff of living together.</p>
        <div className="hero-action-row"><Link className="hero-action" to="/board">Take a look around <ArrowRight size={15} /></Link><span className="hero-members-note"><Users size={14} /> {household.members.length} roomies under one roof</span></div>
      </div>
      <div className="hero-mascot-wrap"><span className="hero-orbit hero-orbit-one" /><span className="hero-orbit hero-orbit-two" /><div className="hero-mascot-disc"><Mascot size="dashboard" /><span className="mascot-caption">Little Homi</span></div><span className="hero-twinkle hero-twinkle-one">✦</span><span className="hero-twinkle hero-twinkle-two">✳</span><span className="hero-float-chip"><Sparkles size={13} /> a little more in sync</span></div>
      <div className="hero-bottom-line"><span>Better Living. Less Drama.</span><span>THE ROOMIE THAT NEVER TAKES SIDES</span></div>
    </section>
    <section className="roommates-section"><SectionHeading eyebrow="THE PEOPLE AT HOME" title="My roommates" /><div className="roommate-strip">{household.members.map((member) => <div className="roommate-card" key={member.id}><Avatar member={member} size="large" /><div className="roommate-info"><strong>{member.name}{member.id === activeMember?.id && <span className="you-pill">you</span>}</strong><span>{member.bio || (member.id === activeMember?.id ? 'Your cozy corner' : 'Part of the household')}</span></div><span className="roommate-status" title="In the household" /></div>)}</div></section>
    <div className="dashboard-grid">
      <section className="dash-card board-card"><SectionHeading eyebrow="ON THE FRIDGE" title="House Board" to="/board" /><div className="board-preview-list">{household.announcements.slice(0, 2).map((item, index) => <article className="board-preview" key={item.id}><div className={`board-marker board-marker--${index === 0 ? 'sage' : 'peach'}`}><MessageCircle size={16} /></div><div className="board-preview-content"><div className="preview-meta"><span>{item.category}</span><span>·</span><span>{item.author_name}</span></div><p>{item.body}</p></div></article>)}{!household.announcements.length && <p className="empty-line">A fresh board, ready for your first note.</p>}</div><Link className="card-bottom-link" to="/board">Add a note <ArrowRight size={14} /></Link></section>
      <section className="dash-card chores-card"><SectionHeading eyebrow="LITTLE THINGS, SHARED" title="Chores" to="/chores" /><div className="chore-preview-list">{openChores.map((chore) => <label className="chore-row" key={chore.id}><button className="check-circle" aria-label={`Mark ${chore.title} complete`} onClick={() => toggleChore(chore)} /><span className="chore-title">{chore.title}<small>{chore.assignee_name}</small></span><span className={`due-pill ${chore.due_label === 'Today' ? 'due-pill--today' : ''}`}>{chore.due_label}</span></label>)}{!openChores.length && <p className="empty-line">All caught up. Enjoy the clear counter.</p>}</div><Link className="card-bottom-link" to="/chores">Open chore list <ArrowRight size={14} /></Link></section>
      <section className="dash-card bills-card"><SectionHeading eyebrow="THE SHARED STUFF" title="Bills & Rent" to="/bills" /><div className="bill-total"><div><span>Still to settle</span><strong>${totalDue.toFixed(2)}</strong></div><span className="bill-icon"><Coins size={19} /></span></div><div className="bill-preview-list">{household.expenses.slice(0, 2).map((expense) => <div className="bill-row" key={expense.id}><span className="bill-dot" /><span>{expense.title}</span><strong>${Number(expense.amount).toFixed(2)}</strong></div>)}</div><Link className="card-bottom-link" to="/bills">View shared expenses <ArrowRight size={14} /></Link></section>
      <Link to="/ask" className="ask-card"><div className="ask-card-copy"><span className="eyebrow-small">A LITTLE HELP, WITHOUT THE DRAMA</span><h2>Talk it through<br />with <span>homi.</span></h2><p>Need a neutral ear? Little Homi can help everyone find a way forward.</p><span className="ask-cta">Meet your mediator <ArrowRight size={15} /></span></div><div className="ask-mascot-bubble"><span className="bubble-sparkle">✦</span><Mascot size="ask" /></div><span className="ask-card-foot">A trusted AI companion for your household <span>·</span> here for your home, never takes sides</span></Link>
      <section className="dash-card rules-card"><SectionHeading eyebrow="AGREED, TOGETHER" title="House Rules" to="/rules" /><div className="rules-preview-list">{household.rules.slice(0, 3).map((rule, index) => <div className="rule-row" key={rule.id}><span className={`rule-number rule-number--${index}`}>0{index + 1}</span><div><strong>{rule.title}</strong><span>{rule.detail}</span></div><CheckCircle2 size={16} className="rule-check" /></div>)}{!household.rules.length && <p className="empty-line">Your shared agreements will feel at home here.</p>}</div><Link className="card-bottom-link" to="/rules">See all house rules <ArrowRight size={14} /></Link></section>
    </div><footer className="dashboard-footer"><span>Made for the people you come home to.</span><span>homi. <i>·</i> {household.name}</span></footer>
  </div>;
}

function App() {
  return <Routes><Route path="/" element={<Welcome />} /><Route path="/create" element={<CreateHousehold />} /><Route element={<AppShell />}><Route path="/home" element={<Dashboard />} /><Route path="/rules" element={<HouseRulesPage />} /><Route path="/board" element={<HouseBoardPage />} /><Route path="/ask" element={<AskPage />} /><Route path="/chores" element={<ChoresPage />} /><Route path="/bills" element={<BillsPage />} /><Route path="*" element={<NotFound />} /></Route></Routes>;
}

export default App;
