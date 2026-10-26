import { useEffect, useRef, useState } from 'react';
import { Link, useOutletContext, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, CalendarDays, Check, CheckCircle2, CircleHelp, Clock3, Coins, MessageCircle, Pencil, Plus, Send, ShieldCheck, Sparkles, Trash2, Users } from 'lucide-react';
import Mascot from '../components/Mascot.jsx';
import MediationWorkspace from '../components/MediationWorkspace.jsx';
import { api } from '../api.js';

function useHome() { return useOutletContext(); }

function PageHeader({ eyebrow, title, description, icon: Icon, action }) {
  return <div className="feature-page-header"><div><span className="eyebrow-small">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action ? <div className="feature-header-action">{action}</div> : Icon && <span className="feature-page-icon"><Icon size={23} /></span>}</div>;
}
function FeatureCard({ children, className = '' }) { return <section className={`feature-card ${className}`}>{children}</section>; }
function Avatar({ member, size = 'normal' }) {
  const initials = member.name.split(' ').map((part) => part[0]).slice(0, 2).join('');
  return <span className={`avatar avatar--${member.color || 'sage'} avatar--${size}`} aria-label={member.name}>{initials}</span>;
}

export function HouseRulesPage() {
  const { household, activeMember, setHousehold, refreshHousehold } = useHome();
  const [category, setCategory] = useState('Quiet hours');
  const [preference, setPreference] = useState('');
  const [changeNotes, setChangeNotes] = useState({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const categories = ['Quiet hours', 'Guests', 'Shared spaces', 'Cleanliness', 'Noise', 'Shared items', 'Other'];
  const contributorCount = new Set(household.rule_preferences.map((item) => item.member_id)).size;

  async function savePreference(event) {
    event.preventDefault();
    if (!preference.trim()) return;
    setBusy('preference'); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/rules/preferences`, {
        method: 'POST', body: JSON.stringify({ member_id: activeMember.id, category, preference: preference.trim() }),
      });
      setHousehold(updated); setPreference(''); setNotice(`Saved for ${activeMember.name}.`);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function generateProposals() {
    setBusy('generate'); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/rules/proposals/generate`, {
        method: 'POST', body: JSON.stringify({ member_id: activeMember.id }),
      });
      setHousehold(updated); setNotice('Little Homi has drafted proposals for everyone to review.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function decide(proposal, decision) {
    const note = changeNotes[proposal.id] || '';
    setBusy(`${proposal.id}:${decision}`); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/rules/proposals/${proposal.id}/decision`, {
        method: 'POST', body: JSON.stringify({ member_id: activeMember.id, decision, note }),
      });
      setHousehold(updated);
      setNotice(decision === 'approve' ? 'Your approval was recorded.' : decision === 'reject' ? 'Your response was recorded.' : 'Your change request was shared with the household.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function revise(proposal) {
    setBusy(`${proposal.id}:revise`); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/rules/proposals/${proposal.id}/revise`, {
        method: 'POST', body: JSON.stringify({ member_id: activeMember.id }),
      });
      setHousehold(updated); setNotice('A revised draft is ready. Everyone needs to review it again.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  return <div className="feature-page page-enter">
    <PageHeader eyebrow="A HOME THAT FEELS LIKE EVERYONE'S" title="House Rules" description="Share what helps you feel at home. Little Homi can help turn different needs into agreements everyone can review." icon={ShieldCheck} />
    <div className="rule-status-banner"><span className="rule-status-icon"><CheckCircle2 size={18} /></span><div><strong>Your household agreements</strong><span>Only rules approved by every roommate become active.</span></div><span className="approved-badge">{household.rules.length} active</span></div>

    <div className="rules-workflow-grid">
      <FeatureCard className="rules-preference-card">
        <div className="rules-section-heading"><div><span className="eyebrow-small">FIRST, HEAR EVERYONE</span><h2>What matters at home?</h2></div><span className="rules-step">01</span></div>
        <p className="rules-intro">Sharing a preference helps Little Homi spot where expectations overlap or differ. Switch roommate profiles in the top bar to add each person's view.</p>
        <form className="rules-preference-form" onSubmit={savePreference}>
          <label className="field-label" htmlFor="rule-category">What is it about?</label>
          <select id="rule-category" value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item}>{item}</option>)}</select>
          <label className="field-label" htmlFor="rule-preference">As {activeMember.name}, what would feel fair?</label>
          <textarea id="rule-preference" value={preference} onChange={(event) => setPreference(event.target.value)} maxLength={600} rows={4} placeholder="For example: I'd like a heads-up before overnight guests, and a quiet house after 10 on weeknights." />
          <div className="compose-footer"><span>{preference.length}/600 · Shared with your household</span><button className="button button--primary" type="submit" disabled={busy === 'preference' || preference.trim().length < 10}>{busy === 'preference' ? 'Saving…' : 'Save preference'} <Check size={15} /></button></div>
        </form>
        <div className="rules-preference-list"><div className="rules-list-heading"><strong>Roommate preferences</strong><span>{contributorCount} of {household.members.length} have shared</span></div>
          {household.rule_preferences.length ? household.rule_preferences.map((item) => <article className="preference-row" key={item.id}><span className="preference-dot" /><div><div className="preference-meta"><strong>{item.member_name}</strong><span>{item.category}</span></div><p>{item.preference}</p></div></article>) : <p className="rules-empty">Preferences will appear here as roomies share them.</p>}
        </div>
      </FeatureCard>

      <FeatureCard className="rules-agent-card">
        <div className="rules-section-heading"><div><span className="eyebrow-small">A NEUTRAL LITTLE HELPER</span><h2>Find common ground</h2></div><span className="rules-step">02</span></div>
        <div className="rules-agent-art"><Mascot size="tiny" /><div><strong>Little Homi listens first.</strong><span>GPT-6 Luna · high reasoning</span></div><Sparkles size={18} /></div>
        <p className="rules-intro">Once at least two roommates have shared preferences, Little Homi can suggest practical, balanced drafts. Nothing becomes a rule until every roommate approves.</p>
        <button className="button button--primary rules-generate-button" onClick={generateProposals} disabled={busy === 'generate' || contributorCount < 2}>
          {busy === 'generate' ? 'Comparing preferences…' : 'Draft house-rule ideas'} <ArrowRight size={15} />
        </button>
        {contributorCount < 2 && <span className="rules-helper">A second roommate needs to share a preference first.</span>}
        <div className="rules-neutral-note"><ShieldCheck size={16} /><span>Little Homi suggests. Your household decides. Preference text is sent securely to the backend AI service for drafting.</span></div>
      </FeatureCard>
    </div>

    {(error || notice) && <p className={error ? 'form-error rules-feedback' : 'rules-feedback rules-feedback--success'} role={error ? 'alert' : 'status'}>{error || notice}</p>}

    <div className="rules-proposals-heading"><div><span className="eyebrow-small">EVERY VOICE COUNTS</span><h2>Drafts for the household</h2></div><button className="button button--light" onClick={refreshHousehold} disabled={Boolean(busy)}>Refresh responses</button></div>
    {household.rule_proposals.length ? <div className="rules-proposal-list">{household.rule_proposals.map((proposal, index) => {
      const myApproval = proposal.approvals.find((item) => item.member_id === activeMember.id);
      const pendingCount = proposal.approvals.filter((item) => item.decision === 'pending').length;
      const stateLabels = { open: `Waiting on ${pendingCount} roommate${pendingCount === 1 ? '' : 's'}`, active: 'Active · everyone approved', rejected: 'Not approved', changes_requested: 'Changes requested', superseded: 'Revised draft available' };
      return <FeatureCard className="rules-proposal-card" key={proposal.id}>
        <div className="proposal-card-top"><div><span className={`rule-number rule-number--${index % 3}`}>{String(index + 1).padStart(2, '0')}</span><span className="eyebrow-small">{proposal.category}</span></div><span className={`proposal-status proposal-status--${proposal.status}`}>{stateLabels[proposal.status] || proposal.status}</span></div>
        <h3>{proposal.title}</h3><p className="proposal-detail">{proposal.detail}</p>{proposal.rationale && <p className="proposal-rationale"><Sparkles size={14} /> {proposal.rationale}</p>}
        {proposal.revised_from_id && <span className="proposal-revision-label">Revised after roommate feedback · everyone votes again</span>}
        <div className="proposal-approvals"><div className="rules-list-heading"><strong>Roommate responses</strong><span>{proposal.approved_count} of {proposal.required_approvals} approved</span></div><div className="approval-pills">{proposal.approvals.map((approval) => <span className={`approval-pill approval-pill--${approval.decision}`} key={approval.member_id}><span />{approval.member_name}<small>{approval.decision === 'changes_requested' ? 'asked for a change' : approval.decision}</small></span>)}</div></div>
        {proposal.approvals.filter((approval) => approval.decision === 'changes_requested' && approval.note).map((approval) => <p className="change-request-note" key={`${proposal.id}:${approval.member_id}`}><strong>{approval.member_name}'s change request:</strong> {approval.note}</p>)}
        {proposal.status === 'open' && myApproval?.decision === 'pending' && <div className="proposal-actions">
          <textarea value={changeNotes[proposal.id] || ''} onChange={(event) => setChangeNotes((current) => ({ ...current, [proposal.id]: event.target.value }))} maxLength={500} rows={2} placeholder="Optional note for your response; required when requesting a change…" />
          <div><button className="button button--primary" onClick={() => decide(proposal, 'approve')} disabled={Boolean(busy)}>Approve</button><button className="button button--light" onClick={() => decide(proposal, 'request_changes')} disabled={Boolean(busy) || (changeNotes[proposal.id] || '').trim().length < 10}>Request changes</button><button className="button button--quiet" onClick={() => decide(proposal, 'reject')} disabled={Boolean(busy)}>Reject</button></div>
        </div>}
        {proposal.status === 'open' && myApproval && myApproval.decision !== 'pending' && <p className="proposal-your-vote">Your response is saved. The proposal stays inactive until every roommate responds.</p>}
        {proposal.status === 'changes_requested' && myApproval?.decision === 'changes_requested' && <div className="proposal-revise-row"><span>Little Homi will draft a new version. Everyone will vote on the revision again.</span><button className="button button--primary" onClick={() => revise(proposal)} disabled={Boolean(busy)}>{busy === `${proposal.id}:revise` ? 'Revising…' : 'Draft a revision'} <Sparkles size={14} /></button></div>}
      </FeatureCard>;
    })}</div> : <FeatureCard className="rules-empty-proposals"><Mascot size="tiny" /><div><strong>No drafts yet</strong><span>When at least two roommates share preferences, Little Homi can prepare a few ideas here.</span></div></FeatureCard>}

    <div className="rules-active-heading"><span className="eyebrow-small">AGREED, TOGETHER</span><h2>Active house rules</h2></div>
    {household.rules.length ? <div className="feature-rule-grid">{household.rules.map((rule, index) => <FeatureCard className="feature-rule-card" key={rule.id}><div className="feature-rule-top"><span className={`rule-number rule-number--${index % 3}`}>{String(index + 1).padStart(2, '0')}</span><span className="approved-badge"><CheckCircle2 size={13} /> Active</span></div><span className="eyebrow-small">{rule.category}</span><h2>{rule.title}</h2><p>{rule.detail}</p></FeatureCard>)}</div> : <p className="rules-empty">No active agreements yet. A proposal appears here only after every roommate approves it.</p>}
    <div className="phase-note"><Mascot size="tiny" /><p><strong>Everyone deserves a say in the shared rules.</strong><span>Preferences and decisions are saved by roommate profile. Switch profiles to submit each person's response.</span></p></div>
  </div>;
}

export function HouseBoardPage() {
  const { household, activeMember, setHousehold, refreshHousehold } = useHome();
  const [searchParams] = useSearchParams();
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [clarifications, setClarifications] = useState({});
  const [decisionNotes, setDecisionNotes] = useState({});
  const [revisionDrafts, setRevisionDrafts] = useState({});
  const requestKeys = useRef({});
  const revisionKeys = useRef({});

  function requestKey(scope, message) {
    const key = `${scope}:${message}`;
    if (!requestKeys.current[key]) requestKeys.current[key] = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return requestKeys.current[key];
  }

  useEffect(() => {
    const postId = searchParams.get('post');
    if (!postId) return;
    requestAnimationFrame(() => document.getElementById(`board-post-${postId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
  }, [searchParams, household.announcements]);

  async function submit(event) {
    event.preventDefault();
    if (!body.trim()) return;
    const message = body.trim();
    setBusy('post'); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/announcements`, { method: 'POST', body: JSON.stringify({ author_id: activeMember.id, body: message, category: 'Announcement', idempotency_key: requestKey('new-post', message) }) });
      setHousehold(updated); setBody('');
      delete requestKeys.current[`new-post:${message}`];
      const createdPost = updated.announcements.find((item) => item.id === updated.board_post_id);
      setNotice(createdPost?.ai_status === 'unavailable'
        ? 'Your note was shared as written. Little Homi could not check it, so no approval status is available.'
        : createdPost?.approval_status === 'clarification_needed'
          ? 'Your note is on the Board. Little Homi has one question before roommates can respond.'
          : createdPost?.approval_status === 'pending'
            ? 'Your request is on the Board and waiting for roommate decisions.'
            : 'Your note is on the House Board.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function answerClarification(post) {
    const answer = (clarifications[post.id] || '').trim();
    if (!answer) return;
    setBusy(`${post.id}:clarify`); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/announcements/${post.id}/clarify`, {
        method: 'POST', body: JSON.stringify({ member_id: activeMember.id, version: post.version, answer }),
      });
      setHousehold(updated); setClarifications((items) => ({ ...items, [post.id]: '' }));
      setNotice(updated.announcements.find((item) => item.id === post.id)?.approval_status === 'pending'
        ? 'Thanks. The request is now waiting for roommate decisions.'
        : 'Thanks. Little Homi updated the Board note with that detail.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function decide(post, decision) {
    const note = (decisionNotes[post.id] || '').trim();
    if (decision === 'request_changes' && !note) {
      setError('Add a short note describing the change you would like.');
      return;
    }
    setBusy(`${post.id}:${decision}`); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/announcements/${post.id}/decision`, {
        method: 'POST', body: JSON.stringify({ member_id: activeMember.id, version: post.version, decision, note }),
      });
      setHousehold(updated);
      setNotice(decision === 'approve' ? 'Your approval was recorded.' : decision === 'reject' ? 'Your response was recorded.' : 'Your change request was shared with the author.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function revise(post) {
    const message = (revisionDrafts[post.id] ?? post.original_body).trim();
    if (message.length < 2) return;
    const key = `${post.id}:${message}`;
    if (!revisionKeys.current[key]) revisionKeys.current[key] = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setBusy(`${post.id}:revise`); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/announcements/${post.id}/revise`, {
        method: 'POST', body: JSON.stringify({ member_id: activeMember.id, message, idempotency_key: revisionKeys.current[key] }),
      });
      setHousehold(updated); setRevisionDrafts((items) => ({ ...items, [post.id]: '' }));
      delete revisionKeys.current[key];
      setNotice('The updated version is on the Board. Previous approvals no longer apply.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  function statusLabel(post) {
    if (post.ai_status === 'pending') return 'Little Homi is checking';
    if (post.ai_status === 'unavailable') return 'AI check unavailable';
    if (post.approval_status === 'pending') return 'Waiting for roommate decisions';
    if (post.approval_status === 'approved') return 'Approved by everyone required';
    if (post.approval_status === 'rejected') return 'Not approved';
    if (post.approval_status === 'changes_requested') return 'Changes requested';
    if (post.approval_status === 'clarification_needed') return 'Needs one detail';
    if (post.approval_status === 'no_other_roommates') return 'No other roommates to ask';
    if (post.approval_status === 'response_requested') return 'Waiting for a reply';
    return 'No approval request flagged';
  }

  return <div className="feature-page page-enter"><PageHeader eyebrow="GOOD TO KNOW, RIGHT AT HOME" title="House Board" description="A shared spot for the little updates that keep everyone in the loop." icon={MessageCircle} />
    <div className="board-ai-intro"><div className="board-ai-mascot"><Mascot size="tiny" /></div><div><strong>A thoughtful note, with a little help from Little Homi</strong><p>Write naturally. Homi can summarize, surface relevant active House Rules, and ask for missing details. A post is never permission by itself.</p></div></div>
    <FeatureCard className="board-compose"><form onSubmit={submit}><div className="compose-avatar"><Avatar member={activeMember} /></div><div className="compose-main"><label htmlFor="new-note">What's happening at home?</label><textarea id="new-note" value={body} onChange={(event) => setBody(event.target.value)} maxLength={2_000} placeholder="Share a heads-up, ask for roommate approval, or leave a reminder…" rows={3} /><div className="compose-footer"><span>{body.length}/2,000 · Shared with your household</span><button className="button button--primary" type="submit" disabled={Boolean(busy) || !body.trim()}>{busy === 'post' ? 'Checking with Little Homi…' : 'Post to board'} <Send size={15} /></button></div>{error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="form-success" role="status">{notice}</p>}</div></form></FeatureCard>
    <div className="board-feed-heading"><div><span className="eyebrow-small">SHARED UPDATES & REQUESTS</span><h2>On the board</h2></div><span>{household.announcements.length} posts</span></div>
    <div className="board-feed">{household.announcements.map((item) => {
      const member = household.members.find((person) => person.id === item.author_id);
      const analysis = item.analysis || {};
      const isAuthor = item.author_id === activeMember.id;
      const myApproval = item.approvals?.find((approval) => approval.member_id === activeMember.id);
      const details = [analysis.date, analysis.time, analysis.location, ...(analysis.people_involved || [])].filter(Boolean);
      const canRevise = isAuthor && (item.requires_approval || ['clarification_needed', 'not_assessed'].includes(item.approval_status));
      return <FeatureCard className={`board-feed-item board-feed-item--smart ${item.approval_status === 'pending' ? 'board-feed-item--pending' : ''}`} key={item.id} id={`board-post-${item.id}`}>
        <div className="feed-avatar">{member ? <Avatar member={member} /> : <span className="avatar avatar--sage">h.</span>}</div>
        <div className="feed-content">
          <div className="feed-meta"><strong>{item.author_name}</strong><span>·</span><span className="board-category">{item.category}</span><span className="feed-time"><Clock3 size={13} /> {new Date(item.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</span></div>
          <div className="board-post-heading"><h3>{item.body}</h3><span className={`board-status board-status--${item.approval_status}`}>{statusLabel(item)}</span></div>
          {item.ai_status === 'pending' && <p className="board-muted-note">Little Homi is reviewing this note. No approval has been decided.</p>}
          {item.ai_status === 'unavailable' && <div className="board-ai-unavailable"><AlertTriangle size={16} /><span>AI analysis is unavailable. This was shared as written; no dates, rule checks, or approval status were generated. A post does not grant permission.</span></div>}
          {item.ai_status === 'complete' && <>
            {details.length > 0 && <div className="board-detail-chips">{analysis.date && <span><CalendarDays size={13} /> {analysis.date}</span>}{analysis.time && <span><Clock3 size={13} /> {analysis.time}</span>}{analysis.location && <span>{analysis.location}</span>}{(analysis.people_involved || []).map((person) => <span key={person}><Users size={13} /> {person}</span>)}</div>}
            {analysis.requested_action && <p className="board-requested-action"><strong>Asked of the household</strong> {analysis.requested_action}</p>}
            {(analysis.rule_conflicts || []).map((conflict) => <div className="board-rule-conflict" key={conflict.rule_id}><div><AlertTriangle size={17} /><strong>Possible overlap with {conflict.title}</strong></div><p>{conflict.explanation}</p><small>{conflict.detail} · A heads-up only. Roommates decide what is allowed.</small></div>)}
            {analysis.response_required && <p className="board-response-needed"><CircleHelp size={15} /> Little Homi thinks a roommate reply would help.</p>}
            {analysis.clarification_question && <div className="board-clarification"><strong>One detail would help</strong><p>{analysis.clarification_question}</p>{isAuthor && item.approval_status === 'clarification_needed' && <div className="board-inline-form"><input aria-label="Clarification answer" value={clarifications[item.id] || ''} onChange={(event) => setClarifications((items) => ({ ...items, [item.id]: event.target.value }))} placeholder="Add a short clarification" maxLength={600} /><button className="button button--light" type="button" onClick={() => answerClarification(item)} disabled={Boolean(busy) || !(clarifications[item.id] || '').trim()}>{busy === `${item.id}:clarify` ? 'Saving…' : 'Add detail'}</button></div>}</div>}
            {analysis.rule_conflicts?.length > 0 && item.approval_status === 'pending' && <p className="board-permission-note"><ShieldCheck size={15} /> This activity needs roommate approval before it can be marked approved.</p>}
            {item.approval_status === 'pending' && <div className="board-approval-panel"><div className="board-approval-heading"><ShieldCheck size={17} /><div><strong>Roommate decisions</strong><span>{item.approved_count} of {item.required_approvals} approvals · This request is not approved yet</span></div></div><div className="board-approval-list">{item.approvals.map((approval) => <span key={approval.member_id} className={`board-approval-chip board-approval-chip--${approval.decision}`}><span>{approval.member_name}</span><span>{approval.decision === 'pending' ? 'Response needed' : approval.decision.replace('_', ' ')}</span></span>)}</div>{myApproval?.decision === 'pending' && <div className="board-decision-actions"><textarea aria-label="Optional response or requested change" value={decisionNotes[item.id] || ''} onChange={(event) => setDecisionNotes((items) => ({ ...items, [item.id]: event.target.value }))} maxLength={500} placeholder="Optional note to the author. Add a note to request a change." rows={2} /><div><button className="button button--primary" type="button" onClick={() => decide(item, 'approve')} disabled={Boolean(busy)}>{busy === `${item.id}:approve` ? 'Saving…' : 'Approve'}</button><button className="button button--light" type="button" onClick={() => decide(item, 'reject')} disabled={Boolean(busy)}>{busy === `${item.id}:reject` ? 'Saving…' : 'Decline'}</button><button className="button button--light" type="button" onClick={() => decide(item, 'request_changes')} disabled={Boolean(busy) || !(decisionNotes[item.id] || '').trim()}>{busy === `${item.id}:request_changes` ? 'Saving…' : 'Request a change'}</button></div></div>}</div>}
            {item.approval_status === 'approved' && <p className="board-approved-note"><CheckCircle2 size={16} /> Every required roommate approved this version. Any edit starts a fresh approval round.</p>}
            {item.approval_status === 'rejected' && <p className="board-rejected-note">A roommate declined this request. It is not approved.</p>}
            {item.approval_status === 'changes_requested' && <p className="board-response-needed"><CircleHelp size={15} /> A roommate asked for a change. The previous version cannot be approved.</p>}
            {item.approval_status === 'no_other_roommates' && <p className="board-response-needed"><CircleHelp size={15} /> No other roommate profiles are available to review this request.</p>}
          </>}
          {canRevise && <details className="board-revise"><summary>{item.ai_status === 'unavailable' ? 'Try the AI check again' : item.approval_status === 'approved' ? 'Change this request' : 'Update this request'}</summary><p>A new version resets any previous roommate responses.</p><textarea aria-label="Updated Board request" value={revisionDrafts[item.id] ?? item.original_body} onChange={(event) => setRevisionDrafts((items) => ({ ...items, [item.id]: event.target.value }))} maxLength={2_000} rows={3} /><button className="button button--primary" type="button" onClick={() => revise(item)} disabled={Boolean(busy) || !(revisionDrafts[item.id] ?? item.original_body).trim()}>{busy === `${item.id}:revise` ? 'Rechecking…' : 'Share updated version'}</button></details>}
          <details className="board-original"><summary>See the original note</summary><p>{item.original_body}</p>{item.clarification_text && <p><strong>Author clarification:</strong> {item.clarification_text}</p>}</details>
        </div>
      </FeatureCard>;
    })}{!household.announcements.length && <FeatureCard className="board-empty"><Mascot size="small" /><div><h3>A fresh board for your household</h3><p>Share the first note when your roommates are ready.</p></div></FeatureCard>}</div>
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="form-success board-page-notice" role="status">{notice}</p>}
  </div>;
}

export function AskPage() {
  return <MediationWorkspace />;
}

export function ChoresPage() {
  const { household, activeMember, setHousehold } = useHome();
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState('');
  const [draft, setDraft] = useState({ title: '', assignee_id: activeMember.id, due_date: '', room: '' });
  const [editDraft, setEditDraft] = useState({});
  const done = household.chores.filter((item) => item.completed).length;

  function beginEdit(chore) {
    setEditingId(chore.id);
    setEditDraft({ title: chore.title, assignee_id: chore.assignee_id || '', due_date: chore.due_date || '', room: chore.room || '' });
    setError(''); setNotice('');
  }

  async function create(event) {
    event.preventDefault(); setBusy('create'); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/chores?member_id=${encodeURIComponent(activeMember.id)}`, { method: 'POST', body: JSON.stringify({ ...draft, room: draft.room.trim() || 'Home', assignee_id: draft.assignee_id || null, due_date: draft.due_date || null }) });
      setHousehold(updated); setDraft({ title: '', assignee_id: activeMember.id, due_date: '', room: '' }); setShowCreate(false); setNotice('Your new chore is on the list.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function toggle(chore) {
    setBusy(chore.id); setError(''); setNotice('');
    try { setHousehold(await api(`/api/households/${household.id}/chores/${chore.id}?member_id=${encodeURIComponent(activeMember.id)}`, { method: 'PATCH', body: JSON.stringify({ completed: !chore.completed }) })); }
    catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }
  async function saveEdit(event, chore) {
    event.preventDefault(); setBusy(chore.id); setError(''); setNotice('');
    try {
      setHousehold(await api(`/api/households/${household.id}/chores/${chore.id}?member_id=${encodeURIComponent(activeMember.id)}`, { method: 'PATCH', body: JSON.stringify({ ...editDraft, room: editDraft.room.trim() || 'Home', assignee_id: editDraft.assignee_id || null, due_date: editDraft.due_date || null }) }));
      setEditingId(''); setNotice('Chore details updated.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function remove(chore) {
    setBusy(chore.id); setError(''); setNotice('');
    try { setHousehold(await api(`/api/households/${household.id}/chores/${chore.id}?member_id=${encodeURIComponent(activeMember.id)}`, { method: 'DELETE' })); setNotice('Chore removed.'); }
    catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  return <div className="feature-page page-enter"><PageHeader eyebrow="SMALL THINGS, SHARED FAIRLY" title="Chores" description="A little teamwork goes a long way. Add a task, choose who has it, and check it off together." action={<div className="chores-header-actions"><span className="progress-chip"><CheckCircle2 size={15} /> {done} of {household.chores.length} done</span><button className="button button--primary" type="button" onClick={() => { setShowCreate((value) => !value); setError(''); setNotice(''); }}><Plus size={15} /> Add a chore</button></div>} />
    {showCreate && <FeatureCard className="household-form-card"><div className="household-form-heading"><div><span className="eyebrow-small">ONE LESS THING TO REMEMBER</span><h2>Add a chore</h2></div></div><form className="household-form-grid" onSubmit={create}><label>Task name<input autoFocus value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder="e.g. Take recycling downstairs" minLength={1} maxLength={100} required /></label><label>Room or area<input value={draft.room} onChange={(event) => setDraft({ ...draft, room: event.target.value })} placeholder="Kitchen" maxLength={50} /></label><label>Assigned to<select value={draft.assignee_id} onChange={(event) => setDraft({ ...draft, assignee_id: event.target.value })}><option value="">Unassigned</option>{household.members.map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label><label>Due date<input type="date" value={draft.due_date} onChange={(event) => setDraft({ ...draft, due_date: event.target.value })} /></label><div className="household-form-actions"><button className="button button--primary" type="submit" disabled={busy === 'create'}>{busy === 'create' ? 'Adding…' : 'Add to chores'}</button><button className="button button--light" type="button" onClick={() => setShowCreate(false)}>Cancel</button></div></form></FeatureCard>}
    <FeatureCard className="chores-feature"><div className="feature-list-heading"><div><CalendarDays size={17} /><strong>This week at home</strong></div><span>Tap a circle when it's done</span></div>{household.chores.map((chore) => <div className="feature-chore-item" key={chore.id}><div className={`feature-chore-row ${chore.completed ? 'feature-chore-row--done' : ''}`}><button className={`check-circle ${chore.completed ? 'check-circle--done' : ''}`} onClick={() => toggle(chore)} disabled={busy === chore.id} aria-label={`${chore.completed ? 'Mark incomplete' : 'Mark complete'}: ${chore.title}`}>{chore.completed && <Check size={12} />}</button><div className="feature-chore-title"><strong>{chore.title}</strong><span>{chore.room || 'Home'}</span></div><div className="chore-assignee"><Avatar member={household.members.find((member) => member.id === chore.assignee_id) || { name: chore.assignee_name, color: 'sage' }} /><span>{chore.assignee_name}</span></div><span className={`due-pill ${chore.due_label === 'Today' ? 'due-pill--today' : ''}`}>{chore.due_date ? new Date(`${chore.due_date}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : chore.due_label}</span><div className="chore-row-actions"><button type="button" className="icon-button" aria-label={`Edit ${chore.title}`} onClick={() => editingId === chore.id ? setEditingId('') : beginEdit(chore)}><Pencil size={15} /></button><button type="button" className="icon-button chore-delete" aria-label={`Delete ${chore.title}`} disabled={busy === chore.id} onClick={() => remove(chore)}><Trash2 size={15} /></button></div></div>{editingId === chore.id && <form className="chore-edit-form" onSubmit={(event) => saveEdit(event, chore)}><label>Task name<input value={editDraft.title} onChange={(event) => setEditDraft({ ...editDraft, title: event.target.value })} maxLength={100} required /></label><label>Room<input value={editDraft.room} onChange={(event) => setEditDraft({ ...editDraft, room: event.target.value })} maxLength={50} /></label><label>Assigned to<select value={editDraft.assignee_id} onChange={(event) => setEditDraft({ ...editDraft, assignee_id: event.target.value })}><option value="">Unassigned</option>{household.members.map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label><label>Due date<input type="date" value={editDraft.due_date} onChange={(event) => setEditDraft({ ...editDraft, due_date: event.target.value })} /></label><div className="household-form-actions"><button className="button button--primary" type="submit" disabled={busy === chore.id}>{busy === chore.id ? 'Saving…' : 'Save changes'}</button><button className="button button--light" type="button" onClick={() => setEditingId('')}>Cancel</button></div></form>}</div>)}{!household.chores.length && <div className="household-empty"><Sparkles size={20} /><p>No chores yet. Add the first small task and share the load.</p></div>}</FeatureCard>{error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="form-success" role="status">{notice}</p>}<div className="simple-feature-note"><Sparkles size={17} /><span>Chore updates save to this household. Roommate profiles are switchable demo identities, not secure accounts.</span></div>
  </div>;
}

export function BillsPage() {
  const { household, activeMember, setHousehold } = useHome();
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [amount, setAmount] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [payerId, setPayerId] = useState(activeMember.id);
  const [participants, setParticipants] = useState(household.members.map((member) => member.id));
  const [splitType, setSplitType] = useState('equal');
  const [customShares, setCustomShares] = useState({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const myBalance = household.balances.find((item) => item.member_id === activeMember.id) || { owes_cents: 0, owed_cents: 0, net_cents: 0 };
  const formatMoney = (cents) => `$${(Number(cents || 0) / 100).toFixed(2)}`;

  function resetExpenseForm() {
    setTitle(''); setAmount(''); setDueDate(''); setSplitType('equal'); setCustomShares({});
    setParticipants(household.members.map((member) => member.id)); setPayerId(activeMember.id);
  }

  function toggleParticipant(memberId) {
    setParticipants((current) => {
      const next = current.includes(memberId) ? current.filter((id) => id !== memberId) : [...current, memberId];
      if (!next.includes(payerId)) setPayerId(next[0] || '');
      return next;
    });
  }

  async function createExpense(event) {
    event.preventDefault(); setBusy('create'); setError(''); setNotice('');
    const selected = household.members.map((member) => member.id).filter((id) => participants.includes(id));
    const body = { title: title.trim(), amount, due_date: dueDate || null, payer_id: payerId, participant_ids: selected, split_type: splitType };
    if (splitType === 'custom') body.custom_shares = selected.map((member_id) => ({ member_id, amount: customShares[member_id] || '0' }));
    try {
      setHousehold(await api(`/api/households/${household.id}/expenses?member_id=${encodeURIComponent(activeMember.id)}`, { method: 'POST', body: JSON.stringify(body) }));
      resetExpenseForm(); setShowCreate(false); setNotice('The shared expense was added. Shares and balances are up to date.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function markPaid(expense) {
    setBusy(expense.id); setError(''); setNotice('');
    try {
      const updated = await api(`/api/households/${household.id}/expenses/${expense.id}/shares/${activeMember.id}/paid`, { method: 'POST', body: JSON.stringify({ member_id: activeMember.id }) });
      setHousehold(updated); setNotice(`Your share of “${expense.title}” is marked paid.`);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  const outstanding = household.expense_totals?.outstanding_cents || 0;
  const settled = household.expense_totals?.settled_cents || 0;
  return <div className="feature-page page-enter"><PageHeader eyebrow="THE SHARED STUFF, MADE SIMPLE" title="Bills & Rent" description="A clear snapshot of shared costs, each person's share, and what has been settled." action={<button className="button button--primary" type="button" onClick={() => { setShowCreate((value) => !value); setError(''); setNotice(''); }}>{showCreate ? 'Close' : <><Plus size={15} /> Add an expense</>}</button>} />
    <div className="bill-summary-grid"><FeatureCard className="bill-summary bill-summary--sage"><span>Your shares to settle</span><strong>{formatMoney(myBalance.owes_cents)}</strong><small>{activeMember.name} · outstanding</small><Coins size={21} /></FeatureCard><FeatureCard className="bill-summary"><span>Owed to you</span><strong>{formatMoney(myBalance.owed_cents)}</strong><small>Roommate shares you covered</small><CheckCircle2 size={21} /></FeatureCard></div>
    <div className="expense-overview-line"><span>{formatMoney(outstanding)} still owed across the household</span><span>{formatMoney(settled)} in fully settled expenses</span></div>
    {showCreate && <FeatureCard className="household-form-card expense-create-card"><div className="household-form-heading"><div><span className="eyebrow-small">SHARED, CLEARLY</span><h2>Add an expense</h2></div><span className="expense-form-note">No payments are processed in homi.</span></div><form className="expense-form" onSubmit={createExpense}><div className="household-form-grid"><label>What was it for?<input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Cleaning supplies" minLength={2} maxLength={100} required /></label><label>Total amount ($)<input inputMode="decimal" type="number" min="0.01" max="1000000" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" required /></label><label>Paid upfront by<select value={payerId} onChange={(event) => setPayerId(event.target.value)} required>{household.members.filter((member) => participants.includes(member.id)).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label><label>Due date<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label></div><fieldset className="participant-fieldset"><legend>Who is sharing this expense?</legend><div className="participant-options">{household.members.map((member) => <label key={member.id}><input type="checkbox" checked={participants.includes(member.id)} onChange={() => toggleParticipant(member.id)} /><Avatar member={member} /><span>{member.name}</span></label>)}</div></fieldset><div className="split-choice"><span>How should it be split?</span><label><input type="radio" name="expense-split" checked={splitType === 'equal'} onChange={() => setSplitType('equal')} /> Equally</label><label><input type="radio" name="expense-split" checked={splitType === 'custom'} onChange={() => setSplitType('custom')} /> Custom amounts</label></div>{splitType === 'custom' && <div className="custom-share-grid">{household.members.filter((member) => participants.includes(member.id)).map((member) => <label key={member.id}><span>{member.name}</span><span className="currency-input"><span>$</span><input type="number" min="0.01" step="0.01" inputMode="decimal" value={customShares[member.id] || ''} onChange={(event) => setCustomShares({ ...customShares, [member.id]: event.target.value })} placeholder="0.00" required /></span></label>)}</div>}<div className="household-form-actions"><button className="button button--primary" type="submit" disabled={busy === 'create' || !participants.length || !payerId}>{busy === 'create' ? 'Saving expense…' : 'Add shared expense'}</button><button className="button button--light" type="button" onClick={() => { setShowCreate(false); resetExpenseForm(); }}>Cancel</button><span className="form-footnote-inline">Equal splits distribute any leftover cents consistently.</span></div></form></FeatureCard>}
    <FeatureCard className="expenses-card"><div className="feature-list-heading"><div><Coins size={17} /><strong>Shared expenses</strong></div><span>{household.expenses.length} items</span></div>{household.expenses.map((expense) => <article className="expense-entry" key={expense.id}><div className="expense-row"><span className={`expense-icon ${expense.status === 'Settled' ? 'expense-icon--settled' : ''}`}>{expense.status === 'Settled' ? <Check size={17} /> : <Coins size={17} />}</span><div className="expense-title"><strong>{expense.title}</strong><span>Paid upfront by {expense.payer_name} · {expense.due_date ? new Date(`${expense.due_date}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : expense.due_label}</span></div><div className="expense-split">{expense.participants.length} {expense.participants.length === 1 ? 'roommate' : 'roommates'}</div><strong className="expense-amount">{formatMoney(expense.amount_cents)}</strong><span className={`expense-status ${expense.status === 'Settled' ? 'expense-status--settled' : ''}`}>{expense.status}</span></div><div className="expense-share-list">{expense.shares.map((share) => <div className="expense-share" key={share.member_id}><span className="expense-share-person"><Avatar size="small" member={household.members.find((member) => member.id === share.member_id) || { name: share.member_name, color: 'sage' }} />{share.member_name}{share.member_id === activeMember.id && <small>you</small>}</span><span className="expense-share-amount">{formatMoney(share.amount_cents)}</span>{share.paid ? <span className="share-paid"><Check size={13} /> Paid</span> : share.member_id === activeMember.id ? <button type="button" className="button button--light share-pay-button" onClick={() => markPaid(expense)} disabled={busy === expense.id}>{busy === expense.id ? 'Saving…' : 'Mark my share paid'}</button> : <span className="share-unpaid">To settle</span>}</div>)}</div></article>)}{!household.expenses.length && <div className="household-empty"><Coins size={20} /><p>No shared expenses yet. Add one to make the split easy to see.</p></div>}</FeatureCard>{error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="form-success" role="status">{notice}</p>}<p className="simple-feature-note"><CircleHelp size={17} /> Payments are tracking only—no money moves here. Roommate profile switching is a demo feature, not authentication, so it cannot verify who recorded a payment.</p>
  </div>;
}

export function NotFound() { return <div className="not-found"><span>Oh, this room's not here.</span><Link className="button button--primary" to="/home">Back home <ArrowRight size={16} /></Link></div>; }
