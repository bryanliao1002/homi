import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, Check, CheckCircle2, CircleHelp, Clock3, HeartHandshake, LockKeyhole, MessageCircle, RotateCw, Send, ShieldAlert, Sparkles, Users } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import Mascot from './Mascot.jsx';
import { api } from '../api.js';

const CATEGORIES = ['Dishes & cleanliness', 'Chores', 'Noise & quiet', 'Guests', 'Shared spaces', 'Shared items', 'Other'];
const steps = ['Tell Homi', 'Hear Everyone', 'Find Common Ground', 'Review Agreement', 'Confirm Together'];

function stageFor(status) {
  if (status === 'active') return 4;
  if (['agreement_pending', 'revision_required', 'preparing_agreement'].includes(status)) return 3;
  if (['mediated'].includes(status)) return 2;
  if (['ready', 'clarifications', 'mediating'].includes(status)) return 1;
  return 0;
}

function statusText(status) {
  return ({
    gathering: 'Listening to everyone',
    clarifications: 'A little more to understand',
    ready: 'Ready for common ground',
    mediating: 'Finding a balanced next step',
    mediated: 'A possible path forward',
    preparing_agreement: 'Putting the plan together',
    agreement_pending: 'Waiting for everyone',
    revision_required: 'Roommate feedback to consider',
    active: 'Agreed together',
    safety_support: 'Extra care needed',
    listening_error: 'A retry is available',
    closed: 'Closed',
  })[status] || status;
}

function Panel({ children, className = '' }) { return <section className={`mediation-panel ${className}`}>{children}</section>; }

function Avatar({ person }) {
  const initials = person.name.split(' ').map((part) => part[0]).slice(0, 2).join('');
  return <span className={`avatar avatar--${person.color || 'sage'}`}>{initials}</span>;
}

function AgentActivity({ runs }) {
  if (!runs?.length) return null;
  return <details className="mediation-activity"><summary><Sparkles size={15} /> How Little Homi worked <span>· {runs.length} agent steps</span></summary>
    <div className="agent-run-list">{runs.map((run, index) => <article className="agent-run" key={`${run.agent_name}-${index}`}>
      <div className="agent-run-top"><strong>{({ listening: 'Listening Agent', mediation: 'Mediation Agent', agreement: 'Agreement Agent' })[run.agent_name] || run.agent_name}</strong><span>{run.reasoning_effort} reasoning · {run.latency_ms == null ? 'in progress' : `${(run.latency_ms / 1000).toFixed(1)}s`}</span></div>
      <div className="agent-usage">{run.input_tokens != null && <span>{run.input_tokens.toLocaleString()} input tokens</span>}{run.output_tokens != null && <span>{run.output_tokens.toLocaleString()} output tokens</span>}{run.reasoning_tokens != null && <span>{run.reasoning_tokens.toLocaleString()} reasoning tokens</span>}{run.outcome === 'error' && <span>Run ended with {run.error_code || 'an error'}</span>}</div>
      <ol>{run.traces.map((trace, traceIndex) => <li key={`${trace.event}-${traceIndex}`}><span>{trace.event.replaceAll('_', ' ')}</span>{trace.tool_name && <small>{trace.tool_name.replaceAll('_', ' ')}</small>}</li>)}</ol>
    </article>)}</div>
  </details>;
}

export default function MediationWorkspace() {
  const { household, activeMember } = useOutletContext();
  const [cases, setCases] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [creatingCase, setCreatingCase] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [statement, setStatement] = useState('');
  const [selectedMembers, setSelectedMembers] = useState([]);
  const [hideIdentity, setHideIdentity] = useState(false);
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const [answers, setAnswers] = useState({});
  const [voteNotes, setVoteNotes] = useState({});
  const [modificationNotes, setModificationNotes] = useState({});
  const activeCase = useMemo(() => creatingCase ? null : cases.find((item) => item.id === selectedId) || cases[0] || null, [cases, selectedId, creatingCase]);

  async function loadCases(selectFirst = false) {
    if (!household?.id || !activeMember?.id) return;
    try {
      const result = await api(`/api/households/${household.id}/mediations?member_id=${encodeURIComponent(activeMember.id)}`);
      setCases(result.cases);
      if (selectFirst || !result.cases.some((item) => item.id === selectedId)) setSelectedId(result.cases[0]?.id || '');
      setError('');
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    setLoading(true);
    setCases([]);
    setSelectedId('');
    // Demo profiles share one browser session, so never carry private drafts
    // from one roommate's view into another roommate's profile.
    setStatement('');
    setSelectedMembers([]);
    setHideIdentity(false);
    setRequestKey(crypto.randomUUID());
    setAnswers({});
    setVoteNotes({});
    setModificationNotes({});
    loadCases(true);
  }, [household?.id, activeMember?.id]);

  function replaceCase(updated) {
    setCases((items) => [updated, ...items.filter((item) => item.id !== updated.id)]);
    setSelectedId(updated.id);
    setCreatingCase(false);
  }

  async function createCase(event) {
    event.preventDefault();
    if (!selectedMembers.length) { setError('Choose at least one other roommate involved.'); return; }
    setBusy('create'); setError(''); setNotice('');
    try {
      const result = await api(`/api/households/${household.id}/mediations`, {
        method: 'POST',
        body: JSON.stringify({ member_id: activeMember.id, other_member_ids: selectedMembers, category, statement, hide_identity: hideIdentity, idempotency_key: requestKey }),
      });
      replaceCase(result);
      setStatement(''); setSelectedMembers([]); setHideIdentity(false); setRequestKey(crypto.randomUUID());
      setNotice(result.status === 'safety_support' ? 'Little Homi paused the regular mediation flow and shared support options.' : result.status === 'listening_error' ? 'Your case is saved. Little Homi could not finish its first listening pass, but you can retry.' : 'Your case is open. Little Homi is making room for every perspective.');
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function action(key, path, body, successText = '') {
    if (!activeCase) return;
    setBusy(key); setError(''); setNotice('');
    try {
      const result = await api(`/api/households/${household.id}/mediations/${activeCase.id}${path}`, { method: 'POST', body: JSON.stringify(body) });
      replaceCase(result);
      if (key.startsWith('question:')) {
        const questionId = key.slice('question:'.length);
        setAnswers((values) => {
          const next = { ...values };
          delete next[questionId];
          return next;
        });
      }
      if (successText) setNotice(successText);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  const otherMembers = household.members.filter((member) => member.id !== activeMember.id);
  const currentAgreement = activeCase?.agreements?.[0];
  const myDecision = currentAgreement?.decisions?.find((item) => item.member_id === activeMember.id);
  const currentStage = activeCase ? stageFor(activeCase.status) : 0;

  return <div className="feature-page ask-page mediation-workspace page-enter">
    <div className="feature-page-header mediation-page-heading"><div><span className="eyebrow-small">A NEUTRAL EAR, WHEN YOU NEED ONE</span><h1>Ask homi.</h1><p>A calmer place to hear everyone and find a practical way forward.</p></div><div className="mediation-ai-label"><Mascot size="tiny" /><span><strong>Little Homi is AI</strong><small>Suggestions only. Your household decides.</small></span></div></div>

    <section className="mediation-hero mediation-hero--compact">
      <div className="mediation-scene"><span className="mediation-sun" /><span className="mediation-orbit mediation-orbit-one" /><span className="mediation-orbit mediation-orbit-two" /><Mascot size="workspace" /><span className="mascot-caption">Little Homi</span></div>
      <div className="mediation-copy"><span className="mediation-overline">YOUR HOUSEHOLD'S CALM CORNER</span><h2>Let's make room<br /><em>for every point of view.</em></h2><p>Little Homi listens, helps sort what is known from what still needs a conversation, then offers a balanced plan for roommates to review together.</p><div className="mediation-honesty"><Sparkles size={16} /><span>Homi helps people talk. It does not decide who is right or make binding decisions.</span></div></div>
    </section>

    <div className="mediation-trust-note"><LockKeyhole size={16} /><span>Demo privacy: statements are saved in this household's local database and sent by the backend to the course AI service. Each profile view shows its own raw statement. Profile switching is not sign-in, so it cannot guarantee privacy or anonymity. Avoid sharing highly sensitive details.</span></div>

    <div className="mediation-layout">
      <aside className="mediation-case-rail">
        <div className="mediation-rail-heading"><div><span className="eyebrow-small">YOUR HOUSEHOLD</span><h2>Mediation cases</h2></div><span className="mediation-case-count">{cases.length}</span></div>
        {cases.map((item) => <button type="button" className={`mediation-case-link ${item.id === activeCase?.id ? 'mediation-case-link--active' : ''}`} key={item.id} onClick={() => { setSelectedId(item.id); setCreatingCase(false); setError(''); setNotice(''); }}><span className="case-link-top"><strong>{item.category}</strong><span className={`case-status-dot case-status-dot--${item.status}`} /></span><span>{item.participants.map((person) => person.name).join(' · ')}</span><small>{statusText(item.status)}</small></button>)}
        {cases.length > 0 && <button type="button" className="button button--light mediation-new-case-button" disabled={Boolean(busy)} onClick={() => { setCreatingCase(true); setError(''); setNotice(''); setStatement(''); setSelectedMembers([]); setHideIdentity(false); setRequestKey(crypto.randomUUID()); }}><MessageCircle size={14} /> Start a new conversation</button>}
        {!loading && !cases.length && <p className="mediation-rail-empty">Your first conversation can start here.</p>}
        {loading && <p className="mediation-rail-empty">Checking in…</p>}
      </aside>

      <div className="mediation-main-column">
        {!activeCase && <Panel className="mediation-start-panel"><div className="mediation-section-title"><span className="mediation-section-icon"><MessageCircle size={18} /></span><div><span className="eyebrow-small">START WITH WHAT'S HAPPENING</span><h2>Tell Homi a little about it.</h2></div></div><p className="mediation-intro">Describe the everyday disagreement in your own words. You will be able to choose who is involved and everyone will get a chance to share their perspective.</p>
          <form className="mediation-form" onSubmit={createCase}>
            <label className="mediation-field"><span>What is it about?</span><select value={category} onChange={(event) => setCategory(event.target.value)}>{CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></label>
            <fieldset className="mediation-participant-pick"><legend>Who is involved? <small>Choose at least one other roommate.</small></legend><div>{otherMembers.map((member) => <label className="mediation-person-choice" key={member.id}><input type="checkbox" checked={selectedMembers.includes(member.id)} onChange={(event) => setSelectedMembers((ids) => event.target.checked ? [...ids, member.id] : ids.filter((id) => id !== member.id))} /><Avatar person={member} /><span><strong>{member.name}</strong><small>{member.bio || 'Roommate'}</small></span></label>)}</div></fieldset>
            <label className="mediation-field"><span>What would you like Little Homi to understand?</span><textarea value={statement} onChange={(event) => setStatement(event.target.value)} maxLength={4000} rows={5} minLength={20} required placeholder="Share what happened from your perspective, what matters to you, and what a good next step could look like…" /><small>{statement.length}/4000 · Aim for specific details; you do not need to prove who is right.</small></label>
            <label className="mediation-anonymity"><input type="checkbox" checked={hideIdentity} onChange={(event) => setHideIdentity(event.target.checked)} /><span><strong>Try to hide my name in shared summaries</strong><small>This masks your name in the app and agent input when possible. Other roommates may still recognize details, and this demo cannot guarantee anonymity.</small></span></label>
            <div className="mediation-submit-row"><span><ShieldAlert size={15} /> Not for urgent danger, abuse, or threats.</span><button className="button button--primary" type="submit" disabled={busy === 'create' || !statement.trim() || !selectedMembers.length}>{busy === 'create' ? 'Opening a conversation…' : 'Start a conversation'} <ArrowRight size={15} /></button></div>
          </form>
        </Panel>}

        {activeCase && <>
          <Panel className="mediation-active-case">
            <div className="mediation-case-heading"><div><span className="eyebrow-small">A SHARED CONVERSATION · {activeCase.category.toUpperCase()}</span><h2>{activeCase.category}</h2><p>Started {new Date(activeCase.created_at).toLocaleDateString(undefined, { month: 'long', day: 'numeric' })} · {statusText(activeCase.status)}</p></div><span className={`mediation-status-pill mediation-status-pill--${activeCase.status}`}><span />{statusText(activeCase.status)}</span></div>
            <ol className="mediation-progress" aria-label="Mediation progress">{steps.map((item, index) => <li className={`${index < currentStage ? 'is-done' : ''} ${index === currentStage ? 'is-current' : ''}`} key={item}><span>{index < currentStage ? <Check size={13} /> : index + 1}</span><small>{item}</small></li>)}</ol>
            {activeCase.status === 'safety_support' ? <div className="mediation-safety-panel"><span><ShieldAlert size={21} /></span><div><strong>Let's take this seriously.</strong><p>{activeCase.safety_guidance}</p></div></div> : <>
              {activeCase.listening_summary && <div className="mediation-listening-summary"><span className="listening-sparkle"><Sparkles size={16} /></span><div><span className="eyebrow-small">WHAT LITTLE HOMI HEARD</span><p>{activeCase.listening_summary}</p></div></div>}
              <div className="mediation-participants"><div className="mediation-block-heading"><div><Users size={16} /><strong>Hear everyone</strong></div><span>{activeCase.statement_count} of {activeCase.participant_count} perspectives shared</span></div><div className="mediation-participant-list">{activeCase.participants.map((person) => <div className="mediation-participant" key={person.member_id}><Avatar person={person} /><span><strong>{person.name}</strong><small>{person.submitted ? 'Perspective shared' : 'Response pending'}</small></span><span className={`participant-check ${person.submitted ? 'participant-check--done' : ''}`}>{person.submitted ? <Check size={13} /> : <Clock3 size={13} />}</span></div>)}</div></div>
              {activeCase.my_statement && <details className="private-statement"><summary><LockKeyhole size={14} /> Your private statement</summary><p>{activeCase.my_statement}</p></details>}
              {!activeCase.all_perspectives_submitted && !activeCase.participants.find((person) => person.member_id === activeMember.id)?.submitted && <form className="mediation-response-form" onSubmit={(event) => { event.preventDefault(); action('statement', '/statements', { member_id: activeMember.id, statement: modificationNotes[activeCase.id] || '' }, 'Your perspective is saved.'); setModificationNotes((notes) => ({ ...notes, [activeCase.id]: '' })); }}><label className="mediation-field"><span>Your perspective</span><textarea value={modificationNotes[activeCase.id] || ''} onChange={(event) => setModificationNotes((notes) => ({ ...notes, [activeCase.id]: event.target.value }))} minLength={20} maxLength={4000} rows={4} placeholder="What do you see differently? What matters to you? What would feel fair?" /><small>Your words remain private to your profile in this demo. The summary is shared with case participants.</small></label><button type="submit" className="button button--primary" disabled={busy === 'statement' || (modificationNotes[activeCase.id] || '').trim().length < 20}>{busy === 'statement' ? 'Sharing your perspective…' : 'Share my perspective'} <Send size={14} /></button></form>}
              {activeCase.all_perspectives_submitted && activeCase.questions?.length > 0 && <div className="mediation-clarifications"><div className="mediation-block-heading"><div><CircleHelp size={16} /><strong>A couple of things to clarify</strong></div><span>Answer, or mark unknown</span></div>{activeCase.questions.map((question) => <div className="mediation-question" key={question.id}><p>{question.question}</p>{question.my_responded ? <div className="clarification-saved"><CheckCircle2 size={14} /> {question.my_marked_unknown ? 'Marked as unknown' : 'Your answer is saved'} <small>{question.response_count}/{question.required_responses} responses</small></div> : <form onSubmit={(event) => { event.preventDefault(); action(`question:${question.id}`, `/clarifications/${question.id}`, { member_id: activeMember.id, answer: answers[question.id] || '', mark_unknown: false }); }}><textarea value={answers[question.id] || ''} onChange={(event) => setAnswers((values) => ({ ...values, [question.id]: event.target.value }))} maxLength={600} rows={2} placeholder="A short answer is plenty…" /><div><button className="button button--light" type="button" disabled={busy === `question:${question.id}`} onClick={() => action(`question:${question.id}`, `/clarifications/${question.id}`, { member_id: activeMember.id, answer: '', mark_unknown: true })}>I’m not sure</button><button className="button button--primary" type="submit" disabled={busy === `question:${question.id}` || (answers[question.id] || '').trim().length < 5}>Save answer</button></div></form>}</div>)}</div>}
              {activeCase.status === 'listening_error' && <button className="button button--light mediation-action-button" onClick={() => action('listen', '/listen', { member_id: activeMember.id }, 'Little Homi has listened again.')} disabled={Boolean(busy)}>{busy === 'listen' ? 'Listening…' : 'Retry listening'} <RotateCw size={14} /></button>}
              {activeCase.status === 'ready' && <div className="mediation-next-step"><div><span className="eyebrow-small">EVERYONE HAS HAD A TURN</span><strong>Ready to look for common ground?</strong><small>Little Homi will compare perspectives and approved house rules, while calling out what remains uncertain.</small></div><button className="button button--primary" onClick={() => action('mediate', '/mediate', { member_id: activeMember.id }, 'Little Homi has prepared a balanced next step.')} disabled={Boolean(busy)}>{busy === 'mediate' ? 'Listening closely…' : 'Find common ground'} <ArrowRight size={15} /></button></div>}
              {activeCase.mediation && <div className="mediation-analysis"><div className="mediation-analysis-heading"><span className="eyebrow-small">A POSSIBLE WAY FORWARD</span><span><HeartHandshake size={15} /> A suggestion, not a verdict</span></div><h3>There may be a way to make this easier.</h3><p className="mediation-resolution">{activeCase.mediation.proposed_resolution}</p>
                <div className="mediation-analysis-grid">{[
                  ['Shared ground', activeCase.mediation.common_ground],
                  ['Reported, not verified', activeCase.mediation.reported_claims],
                  ['Supported information', activeCase.mediation.supported_information],
                  ['Still uncertain', activeCase.mediation.uncertainties],
                  ['Relevant house rules', activeCase.mediation.rule_analysis?.map((rule) => `${household.rules.find((item) => item.id === rule.rule_id)?.title || 'Approved rule'}: ${rule.relationship}`)],
                ].filter(([, list]) => list?.length).map(([title, list]) => <div className="mediation-analysis-item" key={title}><strong>{title}</strong><ul>{list.map((text, index) => <li key={`${title}-${index}`}>{typeof text === 'string' ? text : text.relationship}</li>)}</ul></div>)}</div>
              </div>}
              {activeCase.status === 'mediated' && <div className="mediation-next-step agreement-next"><div><span className="eyebrow-small">MAKE IT PRACTICAL</span><strong>Would a small shared plan help?</strong><small>Little Homi can turn this suggestion into responsibilities and timing. Everyone involved reviews it independently.</small></div><button className="button button--primary" onClick={() => action('agreement', '/agreements', { member_id: activeMember.id }, 'A draft is ready for every roommate to review.')} disabled={Boolean(busy)}>{busy === 'agreement' ? 'Preparing a draft…' : 'Prepare an agreement'} <ArrowRight size={15} /></button></div>}
              {activeCase.status === 'revision_required' && <div className="mediation-revision-notice"><Sparkles size={17} /><span>A roommate did not approve this version. Their feedback pauses activation; a new version needs fresh approvals from everyone.</span></div>}
              {currentAgreement && <section className={`mediation-agreement-card ${currentAgreement.status === 'active' ? 'mediation-agreement-card--active' : ''}`}><div className="agreement-heading"><div><span className="eyebrow-small">{currentAgreement.status === 'active' ? 'CONFIRMED TOGETHER' : `PROPOSAL · VERSION ${currentAgreement.version}`}</span><h3>{currentAgreement.title}</h3></div><span className={`agreement-status agreement-status--${currentAgreement.status}`}>{currentAgreement.status === 'active' ? 'Active agreement' : currentAgreement.status === 'revision_required' ? 'Changes needed' : currentAgreement.status}</span></div><p className="agreement-summary">{currentAgreement.summary}</p><div className="agreement-responsibilities">{currentAgreement.responsibilities.map((item, index) => <div className="agreement-task" key={`${item.member_id}-${index}`}><CheckCircle2 size={16} /><div><strong>{item.member_name}</strong><span>{item.action}</span></div>{item.deadline && <small>{item.deadline}</small>}</div>)}</div>{currentAgreement.follow_up && <div className="agreement-follow-up"><Clock3 size={14} />{currentAgreement.follow_up}</div>}
                <div className="agreement-votes"><div className="mediation-block-heading"><div><Users size={15} /><strong>Roommate responses</strong></div><span>{currentAgreement.approved_count} of {currentAgreement.required_approvals} approved</span></div><div className="agreement-vote-list">{currentAgreement.decisions.map((decision) => <span className={`agreement-vote agreement-vote--${decision.decision}`} key={decision.member_id}><span className="vote-dot" />{decision.member_name}<small>{decision.decision.replaceAll('_', ' ')}</small></span>)}</div></div>
                {currentAgreement.status === 'pending' && myDecision?.decision === 'pending' && <div className="agreement-response"><label className="mediation-field"><span>Anything you would like to say? <small>Required for a change request.</small></span><textarea value={voteNotes[currentAgreement.id] || ''} onChange={(event) => setVoteNotes((notes) => ({ ...notes, [currentAgreement.id]: event.target.value }))} maxLength={500} rows={2} placeholder="Optional note to help the household understand your response…" /></label><div><button className="button button--primary" onClick={() => action('vote', `/agreements/${currentAgreement.id}/decision`, { member_id: activeMember.id, decision: 'approve', note: voteNotes[currentAgreement.id] || '' }, 'Your approval is recorded. The plan stays pending until everyone approves.') } disabled={Boolean(busy)}>Approve</button><button className="button button--light" onClick={() => action('vote', `/agreements/${currentAgreement.id}/decision`, { member_id: activeMember.id, decision: 'request_changes', note: voteNotes[currentAgreement.id] || '' }, 'Your change request pauses the agreement.') } disabled={Boolean(busy) || (voteNotes[currentAgreement.id] || '').trim().length < 10}>Request a change</button><button className="button button--quiet" onClick={() => action('vote', `/agreements/${currentAgreement.id}/decision`, { member_id: activeMember.id, decision: 'reject', note: voteNotes[currentAgreement.id] || '' }, 'Your response is saved. The draft cannot activate.') } disabled={Boolean(busy)}>Reject</button></div></div>}
                {currentAgreement.status === 'pending' && myDecision?.decision !== 'pending' && <p className="agreement-my-vote">Your response is saved. You cannot change it in this round.</p>}
                {currentAgreement.status === 'revision_required' && ['rejected', 'changes_requested'].includes(myDecision?.decision) && <button className="button button--primary mediation-revise-button" onClick={() => action('revise', `/agreements/${currentAgreement.id}/revise`, { member_id: activeMember.id }, 'A fresh proposal is ready for everyone.')} disabled={Boolean(busy)}>{busy === 'revise' ? 'Revising…' : 'Prepare a revised agreement'} <RotateCw size={14} /></button>}
                {activeCase.agreements.length > 1 && <details className="previous-agreement"><summary>Previous proposal versions ({activeCase.agreements.length - 1})</summary>{activeCase.agreements.slice(1).map((item) => <p key={item.id}>Version {item.version}: {item.title} · {item.status}</p>)}</details>}
              </section>}
              <AgentActivity runs={activeCase.agent_runs} />
            </>}
          </Panel>
          <div className="mediation-bottom-note"><ShieldAlert size={14} /><span>If someone may be in danger, or there are threats, harassment, or abuse, stop here and contact trusted local support. Homi is not an emergency service.</span></div>
        </>}
        {(error || notice) && <p className={error ? 'form-error mediation-feedback' : 'mediation-feedback mediation-feedback--success'} role={error ? 'alert' : 'status'}>{error || notice}</p>}
        <Panel className="mediation-values-panel"><div><Mascot size="tiny" /><span><strong>The Roomie That Never Takes Sides.</strong><small>Roommates decide what works for their home.</small></span></div><span>Better Living. Less Drama.</span></Panel>
      </div>
    </div>
  </div>;
}
