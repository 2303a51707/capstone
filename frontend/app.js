/* =====================================================================
   NyayaVoice - frontend application logic.

   Speech capture uses two paths and prefers whichever is actually available:
     1. The browser's Web Speech API - instant, gives live captions while the
        person is still speaking, and needs nothing installed. Chrome and Edge
        support Indian language locales (te-IN, hi-IN, ta-IN, ...).
     2. MediaRecorder -> POST /api/transcribe -> Whisper on the server. Used when
        the browser has no speech support, when the person picked "auto detect",
        or when path 1 returns nothing usable.

   Both paths end at the same place: editable transcript text that the person
   confirms before anything is analysed.
   ===================================================================== */
const API = '';

const NV = (() => {
  // ------------------------------------------------------------- state
  const state = {
    config: null,
    health: null,
    language: 'te',
    autoDetect: false,
    region: 'Telangana',
    regionalLanguage: 'te',
    station: '',
    mode: 'voice',
    transcript: '',
    analysis: null,
    firBundle: null,
    regionalCopy: null,
    entityEdits: {},
    firEdits: {},
    savedId: null,
    reference: null,
    editing: false,
    activeFirTab: 'en',
  };

  // ------------------------------------------------------------- helpers
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const icons = () => { try { lucide.createIcons(); } catch (e) { /* offline CDN */ } };

  const SCRIPT_CLASS = {
    te: 'te', hi: 'hi', mr: 'mr', ta: 'ta', kn: 'kn', ml: 'ml', bn: 'bn', as: 'bn',
  };
  const scriptClass = code => SCRIPT_CLASS[code] || '';

  function toast(message) {
    const t = $('toast');
    $('toastMsg').textContent = message;
    t.classList.add('show');
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove('show'), 3200);
  }

  async function api(path, options = {}) {
    const response = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = body.detail || body.error || `Request failed (${response.status})`;
      throw Object.assign(new Error(message), { payload: body, status: response.status });
    }
    return body;
  }

  // ------------------------------------------------------------- routing
  function showPage(id) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = $('page-' + id);
    if (page) page.classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (id === 'dashboard') loadDashboard();
    icons();
    // keep the interface language across navigation and re-renders
    if (window.NV_I18N) NV_I18N.refresh(page || document.body);
  }

  function goStep(n) {
    [1, 2, 3, 4, 5].forEach(i => { const el = $('rp-step-' + i); if (el) el.style.display = 'none'; });
    $('rp-step-' + n).style.display = 'block';
    document.querySelectorAll('#progressBar .pstep').forEach(s => {
      const sn = +s.dataset.step;
      s.classList.toggle('done', sn < n);
      s.classList.toggle('now', sn === n);
    });
    document.querySelectorAll('#progressBar .pline').forEach((l, i) => l.classList.toggle('done', i < n - 1));
    showPage('report');
  }

  function newComplaint() {
    state.transcript = ''; state.analysis = null; state.firBundle = null;
    state.regionalCopy = null; state.entityEdits = {}; state.firEdits = {};
    state.savedId = null; state.reference = null;
    $('transcriptArea').style.display = 'none';
    $('recordAgainBtn').style.display = 'none';
    $('voiceContinueBtn').style.display = 'none';
    $('typedText').value = '';
    $('liveCaption').classList.add('hidden');
    goStep(1);
  }

  const toggleA11y = () => $('a11yPanel').classList.toggle('open');
  const toggleSplit = id => $(id).classList.toggle('collapsed');
  const toggleExplain = id => $(id).classList.toggle('open');
  const hideError = () => $('voiceError').classList.add('hidden');

  function showError(title, message) {
    $('voiceErrorTitle').textContent = title;
    $('voiceErrorMsg').textContent = message;
    $('voiceError').classList.remove('hidden');
    icons();
  }

  // ------------------------------------------------------------- bootstrap
  async function init() {
    try {
      state.config = await api('/api/config');
    } catch (e) {
      toast('Could not reach the NyayaVoice API. Is the server running on port 8000?');
      return;
    }
    renderLanguages();
    renderRegions();
    pickLang(state.language);
    pickRegion(state.region);
    checkHealth();
    icons();
  }

  async function checkHealth() {
    const strip = $('statusStrip');
    try {
      const health = await api('/api/health');
      state.health = health;
      const speech = health.speech_recognition.available;
      const browserSpeech = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
      const translate = health.translation.available;
      const engine = health.legal_engine;
      const pdf = health.pdf.engine;
      const pills = [
        pill(speech || browserSpeech,
          speech ? `Speech: Whisper (${health.speech_recognition.model})`
                 : browserSpeech ? 'Speech: browser recognition' : 'Speech unavailable',
          'mic'),
        pill(translate, translate ? `Translation: ${health.translation.active_provider}`
                                  : 'Translation unavailable', 'languages'),
        pill(true, `${engine.ipc_sections} sections + ${engine.extra_provisions} special laws`, 'scale'),
        pill(!!engine.classifier, engine.classifier ? 'ML model loaded' : 'ML model not trained', 'brain-circuit'),
        pill(!!pdf, pdf ? 'PDF export ready' : 'PDF export unavailable', 'file-down'),
      ];
      strip.innerHTML = pills.join('');
      if (!translate) {
        toast('Translation provider unavailable — non-English complaints will not be translated.');
      }
    } catch (e) {
      strip.innerHTML = pill(false, 'API unreachable', 'wifi-off');
    }
    icons();
  }

  const pill = (ok, label, icon) =>
    `<span class="status-pill ${ok ? 'ok' : 'off'}"><i data-lucide="${icon}" class="icon"></i>${esc(label)}</span>`;

  // ------------------------------------------------------------- step 1
  function renderLanguages() {
    $('langGrid').innerHTML = state.config.languages.map(l => `
      <div class="lang-card" data-code="${l.code}" onclick="NV.pickLang('${l.code}')">
        <div class="ln">${esc(l.name)}</div>
        <div class="ln-native ${scriptClass(l.code)}">${esc(l.native)}</div>
        <i data-lucide="check-circle-2" class="check"></i>
      </div>`).join('');
  }

  function renderRegions() {
    $('regionSelect').innerHTML = state.config.regions.map(r =>
      `<option value="${esc(r.name)}" ${r.name === state.region ? 'selected' : ''}>${esc(r.name)} — ${esc(r.language_name)}</option>`
    ).join('');
  }

  function pickLang(code) {
    state.language = code;
    state.autoDetect = false;
    document.querySelectorAll('.lang-card').forEach(c =>
      c.classList.toggle('selected', c.dataset.code === code));
    $('autoDetect').classList.remove('selected');
    const name = languageName(code);
    $('chosenLang').textContent = name;
    $('origLangLabel').textContent = name;
    updateBridge();
  }

  function pickAuto() {
    state.autoDetect = true;
    document.querySelectorAll('.lang-card').forEach(c => c.classList.remove('selected'));
    $('autoDetect').classList.add('selected');
    $('chosenLang').textContent = 'Auto-detect';
    updateBridge();
  }

  function pickRegion(name) {
    state.region = name;
    const region = state.config.regions.find(r => r.name === name);
    state.regionalLanguage = region ? region.language : 'en';
    $('regionalLangLabel').textContent = region ? region.language_name : 'English';
    $('chosenRegion').textContent = name;
    updateBridge();
  }

  const languageName = code =>
    (state.config.languages.find(l => l.code === code) || {}).name || code;

  function updateBridge() {
    const spoken = state.autoDetect ? 'the language you speak' : languageName(state.language);
    const officer = languageName(state.regionalLanguage);
    const same = !state.autoDetect && state.language === state.regionalLanguage;
    $('bridgeSummary').textContent = same
      ? `You speak ${spoken}, and the police station works in ${officer}.`
      : `You speak ${spoken}. The police station works in ${officer}. NyayaVoice bridges that gap.`;
  }

  // ------------------------------------------------------------- step 2
  function setMode(mode) {
    state.mode = mode;
    $('tabVoice').classList.toggle('active', mode === 'voice');
    $('tabText').classList.toggle('active', mode === 'text');
    $('voiceMode').classList.toggle('hidden', mode !== 'voice');
    $('textMode').classList.toggle('hidden', mode !== 'text');
    icons();
  }

  function useTypedText() {
    const text = $('typedText').value.trim();
    if (text.split(/\s+/).length < 4) {
      toast('Please write a little more about what happened.');
      return;
    }
    state.transcript = text;
    showTranscript(text);
  }

  function showTranscript(text) {
    $('transcriptText').value = text;
    $('transcriptArea').style.display = 'block';
    $('recordAgainBtn').style.display = 'inline-flex';
    $('voiceContinueBtn').style.display = 'inline-flex';
    const cls = scriptClass(state.language);
    $('transcriptText').className = 'nv-textarea ' + cls;
    icons();
  }

  function resetRecording() {
    $('transcriptArea').style.display = 'none';
    $('recordAgainBtn').style.display = 'none';
    $('voiceContinueBtn').style.display = 'none';
    $('liveCaption').classList.add('hidden');
    $('liveCaption').innerHTML = '';
    state.transcript = '';
  }

  // ---- recording -----------------------------------------------------
  let recognition = null, mediaRecorder = null, chunks = [];
  let recTimer = null, recSeconds = 0, recording = false, finalText = '';

  const browserSpeechAvailable = () =>
    !!(window.SpeechRecognition || window.webkitSpeechRecognition);

  function toggleRecording() {
    if (recording) { stopRecording(); return; }
    startRecording();
  }

  async function startRecording() {
    hideError();
    finalText = '';
    // Auto-detect needs Whisper: the Web Speech API must be told a locale up front.
    const useBrowser = browserSpeechAvailable() && !state.autoDetect;
    $('asrModeLabel').textContent = useBrowser ? 'Recognition: browser' : 'Recognition: Whisper (server)';

    try {
      await startMediaRecorder(useBrowser);
    } catch (err) {
      showError('Microphone not available',
        'We could not access your microphone. Please allow microphone permission in your browser and try again.');
      return;
    }
    if (useBrowser) startBrowserRecognition();

    recording = true;
    recSeconds = 0;
    $('bigMic').classList.add('recording');
    $('recTimer').style.display = 'block';
    $('listeningLbl').style.display = 'block';
    $('liveCaption').classList.remove('hidden');
    $('liveCaption').innerHTML = '<span class="interim">Listening…</span>';
    updateTimer();
    recTimer = setInterval(() => {
      recSeconds++;
      updateTimer();
      if (recSeconds >= 120) stopRecording();     // hard cap, keeps uploads sane
    }, 1000);
  }

  async function startMediaRecorder(browserPathActive) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = [];
    const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
      .find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t));
    mediaRecorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    mediaRecorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      // If the browser path already produced text, keep it; audio is only the fallback.
      if (browserPathActive && finalText.trim().length > 2) {
        state.transcript = finalText.trim();
        showTranscript(state.transcript);
        return;
      }
      await sendAudioToServer();
    };
    mediaRecorder.start();
  }

  function startBrowserRecognition() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new Recognition();
    const locale = (state.config.languages.find(l => l.code === state.language) || {}).speech || 'en-IN';
    recognition.lang = locale;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = event => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalText += chunk + ' ';
        else interim += chunk;
      }
      $('liveCaption').innerHTML =
        `<span class="${scriptClass(state.language)}">${esc(finalText)}</span>` +
        `<span class="interim ${scriptClass(state.language)}">${esc(interim)}</span>`;
    };
    recognition.onerror = () => { /* the Whisper fallback in onstop covers this */ };
    try { recognition.start(); } catch (e) { recognition = null; }
  }

  function updateTimer() {
    const m = String(Math.floor(recSeconds / 60)).padStart(2, '0');
    const s = String(recSeconds % 60).padStart(2, '0');
    $('recTimer').textContent = `${m}:${s}`;
  }

  function stopRecording() {
    clearInterval(recTimer);
    recording = false;
    $('bigMic').classList.remove('recording');
    $('listeningLbl').style.display = 'none';
    $('recTimer').style.display = 'none';
    if (recognition) { try { recognition.stop(); } catch (e) {} recognition = null; }
    if (recSeconds < 1) {
      if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
      showError('Recording too short', 'Please hold the microphone button conversation open for a few seconds and describe what happened.');
      return;
    }
    if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
  }

  async function sendAudioToServer() {
    $('liveCaption').innerHTML = '<span class="interim">Transcribing on the server…</span>';
    const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' });
    const form = new FormData();
    form.append('audio', blob, 'recording.webm');
    if (!state.autoDetect) form.append('language', state.language);
    try {
      const response = await fetch(API + '/api/transcribe', { method: 'POST', body: form });
      const result = await response.json();
      if (!response.ok || !result.ok) {
        $('liveCaption').classList.add('hidden');
        showError(result.error_code === 'no_speech' ? 'Speech not detected' : 'Could not transcribe',
          result.error || 'Transcription failed. Please try again or type your complaint.');
        return;
      }
      if (result.language_detected && result.language) {
        pickLang(result.language);
        $('chosenLang').textContent = `${result.language_name} (detected)`;
        toast(`Detected language: ${result.language_name}`);
      }
      state.transcript = result.text;
      $('liveCaption').innerHTML = `<span class="${scriptClass(result.language)}">${esc(result.text)}</span>`;
      showTranscript(result.text);
    } catch (err) {
      $('liveCaption').classList.add('hidden');
      showError('Server unreachable', 'The transcription service could not be reached. You can type your complaint instead.');
    }
  }

  // ------------------------------------------------------------- step 3+4
  async function runAnalysis() {
    const text = $('transcriptText').value.trim();
    if (text.split(/\s+/).length < 4) {
      toast('Please describe the incident in a few more words.');
      return;
    }
    state.transcript = text;

    goStep(4);
    $('procScreen').style.display = 'block';
    $('analysisResult').style.display = 'none';
    animateProcessing();

    try {
      const analysis = await api('/api/analyze', {
        method: 'POST',
        body: JSON.stringify({
          text,
          language: state.autoDetect ? null : state.language,
          police_region: state.region,
          police_station: $('stationInput').value.trim() || null,
        }),
      });
      state.analysis = analysis;
      state.entityEdits = {};
      state.language = analysis.original_language;
      state.regionalLanguage = analysis.regional_language;
      renderTranslation(analysis);
      renderAnalysis(analysis);
      finishProcessing();
      goStep(3);
    } catch (err) {
      $('procScreen').style.display = 'none';
      goStep(2);
      showError('Analysis failed', err.message);
    }
  }

  function animateProcessing() {
    const steps = [...document.querySelectorAll('#procSteps .proc-step')];
    steps.forEach(s => { s.className = 'proc-step pending'; });
    let i = 0;
    clearInterval(animateProcessing._t);
    animateProcessing._t = setInterval(() => {
      if (i > 0) steps[i - 1].className = 'proc-step done';
      if (i < steps.length) { steps[i].className = 'proc-step active'; i++; }
      else clearInterval(animateProcessing._t);
    }, 380);
  }

  function finishProcessing() {
    clearInterval(animateProcessing._t);
    document.querySelectorAll('#procSteps .proc-step').forEach(s => s.className = 'proc-step done');
    $('procScreen').style.display = 'none';
    $('analysisResult').style.display = 'block';
    icons();
  }

  function renderTranslation(a) {
    $('origLangLabel').textContent = a.original_language_name;
    $('origBody').className = 'split-body ' + scriptClass(a.original_language);
    $('origBody').textContent = a.original_transcript;
    $('enBody').textContent = a.english_translation;

    const conf = a.translation.confidence;
    if (a.translation.translated && conf) {
      $('translationConfidence').innerHTML = `
        <i data-lucide="badge-check" class="icon" style="color:var(--green)"></i>
        <span style="min-width:170px">Translation quality: ${esc(conf.label)}</span>
        <div class="conf-track"><div class="conf-fill" style="width:${conf.score}%"></div></div>
        <span style="font-weight:700;color:var(--navy-900)">${conf.score}</span>`;
    } else if (!a.translation.translated && a.original_language === 'en') {
      $('translationConfidence').innerHTML =
        `<i data-lucide="info" class="icon" style="color:var(--blue-600)"></i><span>The complaint was already in English — no translation was needed.</span>`;
    } else {
      $('translationConfidence').innerHTML =
        `<i data-lucide="triangle-alert" class="icon" style="color:var(--red)"></i><span>Translation unavailable — the text above is the untranslated original.</span>`;
    }

    $('translationWarnings').innerHTML = (a.warnings || [])
      .filter(w => w.level === 'error')
      .map(w => advisoryHTML(w.message, 'danger', 'triangle-alert')).join('');
    icons();
  }

  const advisoryHTML = (text, kind = '', icon = 'info') =>
    `<div class="advisory ${kind}"><i data-lucide="${icon}" class="icon"></i><div>${esc(text)}</div></div>`;

  const ENTITY_META = {
    complainant_name: ['Complainant', 'user-round'],
    victim_name: ['Victim', 'user-round'],
    accused_name: ['Accused / Suspect', 'user-search'],
    location: ['Location', 'map-pin'],
    incident_date: ['Date', 'calendar'],
    incident_time: ['Time', 'clock'],
    mobile_number: ['Contact Number', 'phone'],
    vehicle_number: ['Vehicle Number', 'car'],
    imei: ['IMEI', 'smartphone'],
    money_involved: ['Money / Value', 'banknote'],
    property_involved: ['Property', 'package'],
    weapon: ['Weapon', 'swords'],
    injuries: ['Injuries', 'bandage'],
    threats: ['Threats', 'message-square-warning'],
    witnesses: ['Witnesses', 'eye'],
  };

  function renderAnalysis(a) {
    $('analysisWarnings').innerHTML = (a.warnings || []).map(w =>
      advisoryHTML(w.message, w.level === 'error' ? 'danger' : '', 'triangle-alert')).join('');

    $('summaryBox').innerHTML =
      `<b style="display:block;font-size:12px;text-transform:uppercase;letter-spacing:.8px;color:var(--blue-600);margin-bottom:6px">Incident Summary</b>${esc(a.summary)}`;

    const c = a.classification;
    $('classificationBox').innerHTML = c ? `
      <div class="confidence" style="margin:16px 0">
        <i data-lucide="${esc(c.icon || 'tag')}" class="icon" style="color:var(--saffron-dark)"></i>
        <span style="min-width:200px">Classified as: <b>${esc(c.label)}</b></span>
        <div class="conf-track"><div class="conf-fill" style="width:${c.confidence}%"></div></div>
        <span style="font-weight:700;color:var(--navy-900)">${c.confidence}%</span>
      </div>
      ${(a.alternative_classifications || []).length ? `<p class="small muted" style="margin:-6px 0 14px">
        Also considered: ${a.alternative_classifications.map(x => `${esc(x.label)} (${x.confidence}%)`).join(' · ')}</p>` : ''}
      ` : advisoryHTML('The incident could not be classified automatically. The duty officer must determine the nature of the complaint.', '', 'help-circle');

    $('entityGrid').innerHTML = Object.entries(ENTITY_META).map(([key, [label, icon]]) => {
      const field = a.entities[key];
      const value = field ? field.value : '';
      const evidence = field && field.evidence ? field.evidence : '';
      return `<div class="entity-card">
        <div class="ec-top"><i data-lucide="${icon}" class="icon"></i><label>${esc(label)}</label></div>
        <input value="${esc(value)}" placeholder="Not provided" data-entity="${key}"
               oninput="NV.editEntity('${key}', this)">
        ${evidence ? `<div class="ec-evidence">from your words: “${esc(evidence)}”</div>` : ''}
      </div>`;
    }).join('');

    const questions = a.extraction_meta.follow_up_questions || [];
    $('followUps').innerHTML = questions.length ? `
      <div class="followups">
        <h5><i data-lucide="list-checks" class="icon"></i> The officer should still ask</h5>
        <p class="tiny muted" style="margin-bottom:8px">These details are missing. NyayaVoice will not fill them in — they stay blank until a person supplies them.</p>
        <ul>${questions.map(q => `<li>${esc(q)}</li>`).join('')}</ul>
      </div>` : '';

    const regime = a.law_regime || {};
    $('lawRegimeNote').innerHTML = advisoryHTML(regime.note || '',
      regime.applicable === 'unknown' ? '' : 'info',
      regime.applicable === 'unknown' ? 'calendar-clock' : 'scale');

    $('provisionList').innerHTML = a.provisions.length
      ? a.provisions.map(provisionHTML).join('')
      : `<div class="empty-state"><i data-lucide="scale" class="icon"></i>
           <h4>No provision reached the confidence threshold</h4>
           <p class="small">The complaint has still been recorded in full for the duty officer to assess.</p></div>`;

    $('advisoryList').innerHTML = (a.advisories || [])
      .map(x => advisoryHTML(`${x.category}: ${x.note}`, '', 'lightbulb')).join('');

    const signals = a.signals_used || [];
    $('signalsBox').innerHTML = `
      <div class="followups" style="margin-top:20px">
        <h5><i data-lucide="brain-circuit" class="icon"></i> How these suggestions were produced</h5>
        <p class="tiny muted">Three independent signals are blended, so no single one decides the outcome.</p>
        <div class="signal-bars">${signals.map(s => `
          <div class="signal-row"><b>${esc(s.name)}</b>
            <div class="signal-track"><div class="signal-fill" style="width:${(s.weight * 100).toFixed(0)}%"></div></div>
            <span>${(s.weight * 100).toFixed(0)}% weight ${s.available ? '' : '· unavailable'}
            ${s.trained_on ? `· trained on ${s.trained_on.toLocaleString()} judgments` : ''}</span>
          </div>`).join('')}</div>
      </div>`;
    icons();
  }

  function provisionHTML(p, index) {
    const relevanceColor = p.relevance === 'High' ? 'var(--green)'
      : p.relevance === 'Medium' ? 'var(--blue-600)' : 'var(--gray-400)';
    const facts = (p.matched_facts || []).map(f =>
      `<li><i data-lucide="check" class="icon"></i> ${esc(f.label)}${f.evidence ? ` — <span class="muted">“${esc(f.evidence)}”</span>` : ''}</li>`).join('');
    const chain = (p.reasoning_chain || []).map((node, i, arr) => `
      <div class="chain-node ${node.final ? 'final' : ''}"><b>${esc(node.step)}:</b> ${esc(node.value)}</div>
      ${i < arr.length - 1 ? '<div class="chain-arrow"><i data-lucide="arrow-down" class="icon"></i></div>' : ''}`).join('');
    const s = p.signals || {};
    return `
    <div class="provision" style="border-left-color:${relevanceColor}">
      <h4><i data-lucide="scale" class="icon" style="color:${relevanceColor}"></i> ${esc(p.offence_name)} — ${esc(p.section_label)}</h4>
      <p class="pv-offence">${esc(p.law_name)}${p.legacy_label ? ` — corresponding to former ${esc(p.legacy_label)}` : ''}</p>
      <div class="pv-meta">
        <span class="pv-chip law">${esc(p.citation)}</span>
        ${p.legacy_label ? `<span class="pv-chip legacy">${esc(p.legacy_label)}</span>` : ''}
        ${p.flag ? `<span class="pv-chip flag">${esc(String(p.flag).replace(/_/g, ' '))}</span>` : ''}
        ${p.training_cases ? `<span class="pv-chip">${p.training_cases.toLocaleString()} cases in dataset</span>` : ''}
      </div>
      <h6>Why it may be relevant</h6>
      <p>${esc(p.matching_reason)}</p>
      ${facts ? `<h6>Relevant facts detected</h6><ul>${facts}</ul>` : ''}
      <div class="pv-foot">
        <button class="btn btn-outline btn-sm" onclick="NV.showProvision('${esc(p.code)}')">View Details</button>
        <span class="relevance" style="background:${p.relevance === 'High' ? 'var(--green-50)' : 'var(--blue-50)'};color:${relevanceColor}">${esc(p.relevance)} relevance · ${p.confidence}%</span>
      </div>
      <button class="btn btn-ghost btn-sm" style="margin-top:8px" onclick="NV.toggleExplain('ex-${index}')"><i data-lucide="brain-circuit" class="icon"></i> Why did NyayaVoice suggest this?</button>
      <div class="explain-panel" id="ex-${index}">
        <div class="chain">${chain}</div>
        <div class="signal-bars" style="margin-top:14px">
          <div class="signal-row"><b>Rule layer</b><div class="signal-track"><div class="signal-fill rule" style="width:${(s.rule_layer || 0) * 100}%"></div></div><span>${((s.rule_layer || 0) * 100).toFixed(0)}%</span></div>
          <div class="signal-row"><b>Statute retrieval</b><div class="signal-track"><div class="signal-fill" style="width:${(s.retrieval_layer || 0) * 100}%"></div></div><span>${((s.retrieval_layer || 0) * 100).toFixed(0)}%</span></div>
          <div class="signal-row"><b>Trained model</b><div class="signal-track"><div class="signal-fill model" style="width:${(s.model_layer || 0) * 100}%"></div></div><span>${((s.model_layer || 0) * 100).toFixed(0)}%</span></div>
        </div>
        <p class="tiny muted" style="margin-top:10px">${esc(p.verification_note || '')}</p>
      </div>
    </div>`;
  }

  function editEntity(key, input) {
    state.entityEdits[key] = input.value.trim();
    input.classList.add('dirty');
  }

  async function showProvision(code) {
    try {
      const p = await api('/api/provisions/' + encodeURIComponent(code));
      openModal(`
        <h3>${esc(p.offence_name)}</h3>
        <p class="small muted">${esc(p.law_name)} · Section ${esc(p.section_number)}</p>
        ${p.bns_section ? `<div class="pv-meta" style="margin-top:12px"><span class="pv-chip law">Current: BNS ${esc(p.bns_section)}</span><span class="pv-chip legacy">Legacy: IPC ${esc(p.section_number)}</span></div>` : ''}
        <h6>Statutory text</h6><p>${esc(p.description)}</p>
        ${(p.elements || []).length ? `<h6>Ingredients to establish</h6><ul>${p.elements.map(e => `<li>${esc(e)}</li>`).join('')}</ul>` : ''}
        <h6>Punishment</h6><p>${esc(p.punishment)}</p>
        <h6>Source</h6><p class="tiny">${esc(p.source || '')}</p>
        <p class="tiny muted" style="margin-top:14px">Verify against the bare act at indiacode.nic.in before any official use.</p>
        <div style="text-align:right;margin-top:18px"><button class="btn btn-primary btn-sm" onclick="NV.closeModal()">Close</button></div>`);
    } catch (e) { toast(e.message); }
  }

  function openModal(html) {
    $('modalHost').innerHTML = `<div class="modal-back" onclick="if(event.target===this)NV.closeModal()"><div class="modal">${html}</div></div>`;
    icons();
  }
  const closeModal = () => { $('modalHost').innerHTML = ''; };

  // ------------------------------------------------------------- step 5
  function mergedEntities() {
    const entities = JSON.parse(JSON.stringify(state.analysis.entities));
    Object.entries(state.entityEdits).forEach(([key, value]) => {
      entities[key] = value
        ? { value, evidence: null, source: 'user', confidence: 'high' }
        : null;
    });
    return entities;
  }

  async function generateFIR() {
    toast('Preparing the FIR draft…');
    try {
      const result = await api('/api/generate-fir', {
        method: 'POST',
        body: JSON.stringify({
          original_transcript: state.analysis.original_transcript,
          english_translation: state.analysis.english_translation,
          original_language: state.analysis.original_language,
          police_region: state.region,
          police_station: $('stationInput').value.trim() || null,
          entities: mergedEntities(),
          provisions: state.analysis.provisions,
          classification: state.analysis.classification,
          reference_number: state.reference,
          include_regional: true,
        }),
      });
      state.firBundle = result.english;
      state.regionalCopy = result.regional;
      state.reference = result.english.fir.reference_number;
      state.firEdits = {};
      renderFIR();
      goStep(5);
    } catch (err) {
      toast('Could not generate the FIR: ' + err.message);
    }
  }

  const regenerate = () => generateFIR().then(() => toast('Draft regenerated from the current information'));

  const FIR_ORDER = [
    ['police_station', 'report_date'], ['reference_number', 'report_time'],
    ['complainant_name', 'complainant_contact'], ['complainant_address', 'victim_name'],
    ['incident_type', 'incident_location'], ['incident_date', 'incident_time'],
  ];
  const FIR_BLOCKS = ['incident_description'];
  const FIR_PAIRS2 = [
    ['property_involved', 'property_value'], ['vehicle_number', 'imei_number'],
    ['weapon_used', 'injuries_reported'], ['accused_details', 'witness_details'],
  ];

  function renderFIR() {
    const tabs = [
      { id: 'en', label: 'English' },
      { id: 'regional', label: state.regionalCopy ? state.regionalCopy.language_name : 'Regional', cls: scriptClass(state.regionalLanguage) },
      { id: 'orig', label: 'Original Transcript' },
      { id: 'bi', label: 'Side-by-Side' },
    ];
    $('firTabs').innerHTML = tabs.map(t =>
      `<button class="fir-tab ${t.cls || ''} ${t.id === state.activeFirTab ? 'active' : ''}" onclick="NV.firTab('${t.id}')">${esc(t.label)}</button>`).join('');

    $('fir-en').innerHTML = firDocHTML(state.firBundle.fir, state.firBundle.field_labels, 'en', true);

    if (state.regionalCopy) {
      const cls = scriptClass(state.regionalCopy.language);
      $('fir-regional').className = 'fir-doc ' + cls + (state.activeFirTab === 'regional' ? '' : ' hidden');
      $('fir-regional').innerHTML =
        (state.regionalCopy.note ? `<p class="tiny muted" style="margin-bottom:14px">${esc(state.regionalCopy.note)}</p>` : '') +
        firDocHTML(state.regionalCopy.fir, state.regionalCopy.labels, state.regionalCopy.language, false);
    }

    const origCls = scriptClass(state.firBundle.original_language);
    $('fir-orig').innerHTML = `
      <div class="fir-letterhead"><h3>Original Voice Transcript</h3>
        <p>Preserved exactly as recorded · Language: ${esc(languageName(state.firBundle.original_language))}</p></div>
      <div class="fir-field"><div class="val ro ${origCls}" style="font-size:16px;line-height:2">${esc(state.firBundle.original_transcript)}</div></div>
      <h5>English translation</h5>
      <div class="fir-field"><div class="val ro">${esc(state.firBundle.english_translation)}</div></div>
      <p class="small muted"><i data-lucide="info" class="icon" style="width:15px;height:15px;vertical-align:-3px"></i> The original transcript is never modified by the system. Where the two differ, the complainant's original statement prevails.</p>`;

    if (state.regionalCopy) {
      const rows = [['incident_description', 'Incident description'], ['incident_location', 'Location'],
        ['incident_date', 'Date'], ['incident_time', 'Time'], ['property_involved', 'Property'],
        ['potentially_relevant_provisions', 'Potential provisions']];
      const cls = scriptClass(state.regionalCopy.language);
      const cell = (fir, key) => {
        const v = fir[key];
        return Array.isArray(v) ? v.map(esc).join('<br>') : esc(v);
      };
      $('fir-bi').innerHTML = `<div class="bilingual">
        <div class="biling-col"><div class="biling-head">English FIR</div>
          ${rows.map(([k, l]) => `<div class="biling-row"><small>${esc(l)}</small><div>${cell(state.firBundle.fir, k)}</div></div>`).join('')}
        </div>
        <div class="biling-col ${cls}"><div class="biling-head">${esc(state.regionalCopy.language_name)} FIR</div>
          ${rows.map(([k, l]) => `<div class="biling-row"><small>${esc(state.regionalCopy.labels[k] || l)}</small><div>${cell(state.regionalCopy.fir, k)}</div></div>`).join('')}
        </div></div>`;
    }
    firTab(state.activeFirTab);
    icons();
  }

  function firDocHTML(fir, labels, langCode, editable) {
    const L = key => esc(labels[key] || key);
    const field = (key, half) => {
      const value = fir[key] ?? '';
      const missing = value === 'Not provided' || value === '' || value === 'None stated';
      return `<div class="fir-field">
        <label>${L(key)}</label>
        <div class="val ro" style="${missing ? 'color:var(--gray-400)' : ''}">${esc(value)}</div>
        ${editable ? `<input class="ed" style="display:none" value="${esc(value)}" data-fir="${key}" oninput="NV.editFir('${key}',this.value)">` : ''}
      </div>`;
    };
    const block = key => {
      const value = fir[key] ?? '';
      return `<h5>${L(key)}</h5><div class="fir-field">
        <div class="val ro" style="font-size:14.5px;line-height:1.85;white-space:pre-wrap">${esc(value)}</div>
        ${editable ? `<textarea class="ed" style="display:none" rows="7" data-fir="${key}" oninput="NV.editFir('${key}',this.value)">${esc(value)}</textarea>` : ''}
      </div>`;
    };
    const provisions = Array.isArray(fir.potentially_relevant_provisions)
      ? fir.potentially_relevant_provisions : [fir.potentially_relevant_provisions];

    return `
      <div class="fir-letterhead">
        <h3 style="letter-spacing:${langCode === 'en' ? '.5px' : '0'}">${esc(fir.document_title)}</h3>
        <p>${L('police_station')}: ${esc(fir.police_station)} &nbsp;·&nbsp; ${esc(fir.district_state)} &nbsp;·&nbsp; ${esc(fir.language_of_this_copy || '')}</p>
      </div>
      <div class="fir-grid2">${FIR_ORDER.flat().map(k => field(k, true)).join('')}</div>
      ${FIR_BLOCKS.map(block).join('')}
      <h5>${L('property_involved')}</h5>
      <div class="fir-grid2">${FIR_PAIRS2.flat().map(k => field(k, true)).join('')}</div>
      <h5>${L('potentially_relevant_provisions')}</h5>
      <div class="fir-field">
        <div class="val ro" style="font-size:14px;line-height:1.9">${provisions.map(esc).join('<br>')}</div>
      </div>
      ${fir.applicable_law_regime ? `<p class="small muted">${esc(fir.applicable_law_regime)}</p>` : ''}
      <div class="sig-row">
        <div class="sig-box">${esc(fir.verification_line)}</div>
        <div class="sig-box">${esc(fir.officer_line)}</div>
      </div>
      <p class="tiny muted" style="margin-top:16px">${esc(fir.ai_notice)}</p>`;
  }

  function firTab(mode) {
    state.activeFirTab = mode;
    document.querySelectorAll('.fir-tab').forEach((t, i) =>
      t.classList.toggle('active', ['en', 'regional', 'orig', 'bi'][i] === mode));
    ['en', 'regional', 'orig', 'bi'].forEach(m => {
      const el = $('fir-' + m);
      if (el) el.classList.toggle('hidden', m !== mode);
    });
  }

  function editFir(key, value) { state.firEdits[key] = value; }

  function toggleEdit() {
    state.editing = !state.editing;
    document.querySelectorAll('#fir-en .ro').forEach(v => v.style.display = state.editing ? 'none' : 'block');
    document.querySelectorAll('#fir-en .ed').forEach(v => v.style.display = state.editing ? 'block' : 'none');
    $('editBtn').innerHTML = state.editing
      ? '<i data-lucide="check" class="icon"></i> Done'
      : '<i data-lucide="pen-line" class="icon"></i> Edit';
    icons();
    toast(state.editing ? 'Inline editing enabled' : 'Edits kept in this draft — use Save Draft to store them');
  }

  const editedFir = () => ({ ...state.firBundle.fir, ...state.firEdits });

  async function saveComplaint(thenDashboard) {
    if (!state.firBundle) { toast('Generate the FIR draft first.'); return; }
    try {
      const a = state.analysis;
      const payload = {
        original_language: a.original_language,
        police_region: state.region,
        police_station: $('stationInput').value.trim() || null,
        regional_language: state.regionalLanguage,
        original_transcript: a.original_transcript,
        english_translation: a.english_translation,
        crime_type: (a.classification || {}).label || null,
        crime_confidence: (a.classification || {}).confidence || null,
        input_mode: state.mode,
        incident_date_iso: a.incident_date_iso,
        summary: a.summary,
        entities: mergedEntities(),
        provisions: a.provisions,
        english_fir: editedFir(),
        regional_fir: state.regionalCopy ? state.regionalCopy.fir : null,
        field_labels: state.firBundle.field_labels,
        regional_labels: state.regionalCopy ? state.regionalCopy.labels : null,
        reference_number: state.reference,
        analysis: { law_regime: a.law_regime, advisories: a.advisories },
      };
      if (state.savedId) {
        await api('/api/complaints/' + state.savedId, {
          method: 'PUT',
          body: JSON.stringify({ english_fir: payload.english_fir, entities: state.entityEdits }),
        });
        toast('Draft updated');
      } else {
        const result = await api('/api/complaints', { method: 'POST', body: JSON.stringify(payload) });
        state.savedId = result.complaint.id;
        toast('Saved as ' + result.complaint.reference_number);
      }
      if (thenDashboard) showPage('dashboard');
    } catch (err) {
      toast('Could not save: ' + err.message);
    }
  }

  async function downloadPDF() {
    if (!state.firBundle) { toast('Generate the FIR draft first.'); return; }
    const button = $('pdfBtn');
    button.innerHTML = '<i data-lucide="loader-circle" class="icon spin"></i> Preparing…';
    icons();
    try {
      const bundle = { ...state.firBundle, fir: editedFir() };
      const result = await api('/api/generate-pdf', {
        method: 'POST',
        body: JSON.stringify({
          fir_bundle: bundle,
          regional_copy: state.regionalCopy,
          copies: 'both',
          include_transcript: true,
        }),
      });
      (result.warnings || []).forEach(w => toast(w));
      const link = document.createElement('a');
      link.href = result.download_url;
      link.download = (state.reference || 'nyayavoice-fir') + '.pdf';
      document.body.appendChild(link);
      link.click();
      link.remove();
      toast(`PDF ready — ${result.pages} pages (${result.languages.join(' + ')})`);
    } catch (err) {
      toast('PDF export failed: ' + (err.payload?.error || err.message));
    } finally {
      button.innerHTML = '<i data-lucide="download" class="icon"></i> Download PDF';
      icons();
    }
  }

  // ------------------------------------------------------------- dashboard
  async function loadDashboard() {
    const card = $('complaintsCard');
    card.innerHTML = '<div style="padding:24px"><div class="skeleton" style="height:40px;margin-bottom:10px"></div><div class="skeleton" style="height:40px;margin-bottom:10px"></div><div class="skeleton" style="height:40px"></div></div>';
    try {
      const query = $('searchInput').value.trim();
      const data = await api('/api/complaints?q=' + encodeURIComponent(query));
      const s = data.stats;
      $('statsGrid').innerHTML = [
        ['Total Complaints', s.total_complaints, 'file-text'],
        ['Draft FIRs', s.draft_firs, 'file-pen'],
        ['Completed Reviews', s.completed_reviews, 'badge-check'],
        ['Languages Used', s.languages_used, 'languages'],
      ].map(([label, num, icon]) =>
        `<div class="stat-card"><div class="st-top"><span class="lbl">${label}</span><i data-lucide="${icon}" class="icon"></i></div><div class="num">${num}</div></div>`).join('');

      card.innerHTML = data.complaints.length ? `
        <table>
          <thead><tr><th>Reference</th><th>Date</th><th>Language</th><th>Incident Type</th><th>Region</th><th>Status</th><th>Action</th></tr></thead>
          <tbody>${data.complaints.map(c => `
            <tr>
              <td style="font-weight:600">${esc(c.reference_number)}</td>
              <td>${new Date(c.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</td>
              <td>${esc(languageName(c.original_language))}</td>
              <td>${esc(c.crime_type || '—')}</td>
              <td>${esc(c.police_region)}</td>
              <td><span class="status ${c.status === 'reviewed' ? 'done' : 'draft'}"><i data-lucide="${c.status === 'reviewed' ? 'check' : 'pen-line'}" class="icon"></i>${esc(c.status)}</span></td>
              <td style="display:flex;gap:6px">
                <button class="btn btn-outline btn-sm" onclick="NV.openComplaint(${c.id})">Open</button>
                <button class="btn btn-ghost btn-sm" onclick="NV.deleteComplaint(${c.id})"><i data-lucide="trash-2" class="icon"></i></button>
              </td>
            </tr>`).join('')}</tbody>
        </table>` : `
        <div class="empty-state"><i data-lucide="folder-open" class="icon"></i>
          <h4>No complaints yet</h4><p class="small">Reported incidents and their FIR drafts will appear here.</p></div>`;
      icons();
    } catch (err) {
      card.innerHTML = `<div class="empty-state"><i data-lucide="wifi-off" class="icon"></i><h4>Could not load complaints</h4><p class="small">${esc(err.message)}</p></div>`;
      icons();
    }
  }

  async function deleteComplaint(id) {
    if (!confirm('Delete this complaint and its FIR draft? This cannot be undone.')) return;
    try {
      await api('/api/complaints/' + id, { method: 'DELETE' });
      toast('Complaint deleted');
      loadDashboard();
    } catch (err) { toast(err.message); }
  }

  async function openComplaint(id) {
    showPage('details');
    $('detailsBody').innerHTML = '<div class="skeleton" style="height:220px"></div>';
    try {
      const c = await api('/api/complaints/' + id);
      renderDetails(c);
    } catch (err) {
      $('detailsBody').innerHTML = `<div class="empty-state"><i data-lucide="triangle-alert" class="icon"></i><h4>${esc(err.message)}</h4></div>`;
      icons();
    }
  }

  function renderDetails(c) {
    const origCls = scriptClass(c.original_language);
    const entities = c.entities.filter(e => e.entity_value && e.entity_value !== 'null');
    const draft = c.draft;
    $('detailsBody').innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;margin-bottom:26px">
        <div><h1 class="sec-title" style="margin-bottom:2px">${esc(c.reference_number)}</h1>
          <p class="sec-sub">Reported ${new Date(c.created_at).toLocaleString('en-IN')} · Language: ${esc(languageName(c.original_language))} · Incident: ${esc(c.crime_type || '—')}</p></div>
        <div style="display:flex;gap:8px;align-items:center">
          <span class="status ${c.status === 'reviewed' ? 'done' : 'draft'}" style="font-size:13px"><i data-lucide="clock" class="icon"></i>${esc(c.status)}</span>
          ${c.status !== 'reviewed' ? `<button class="btn btn-success btn-sm" onclick="NV.markReviewed(${c.id})"><i data-lucide="check" class="icon"></i> Mark Reviewed</button>` : ''}
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1.6fr 1fr;gap:22px" class="details-grid">
        <div style="display:flex;flex-direction:column;gap:22px">
          <div class="card" style="padding:24px">
            <h3 style="font-size:16px;font-weight:800;margin-bottom:14px;display:flex;align-items:center;gap:8px"><i data-lucide="mic" class="icon" style="color:var(--saffron-dark)"></i> Original Voice Transcript</h3>
            <p class="${origCls}" style="font-size:15px;line-height:1.9;background:var(--gray-100);border-radius:11px;padding:16px">${esc(c.original_transcript)}</p>
            <h3 style="font-size:16px;font-weight:800;margin:20px 0 14px;display:flex;align-items:center;gap:8px"><i data-lucide="languages" class="icon" style="color:var(--blue-600)"></i> English Translation</h3>
            <p style="font-size:14.5px;line-height:1.8;background:var(--blue-50);border-radius:11px;padding:16px">${esc(c.english_translation)}</p>
            <h3 style="font-size:16px;font-weight:800;margin:20px 0 14px;display:flex;align-items:center;gap:8px"><i data-lucide="scan-search" class="icon" style="color:var(--green)"></i> Extracted Information</h3>
            <div class="entity-grid" style="grid-template-columns:repeat(auto-fill,minmax(180px,1fr))">
              ${entities.map(e => `<div class="entity-card"><label>${esc((ENTITY_META[e.entity_type] || [e.entity_type])[0])}</label>
                <div style="font-weight:600;font-size:14px;margin-top:4px">${esc(e.entity_value)}</div>
                ${e.edited_by_user ? '<div class="ec-evidence">edited by user</div>' : ''}</div>`).join('') ||
                '<p class="small muted">No entities were extracted.</p>'}
            </div>
          </div>
          <div class="card" style="padding:24px">
            <h3 style="font-size:16px;font-weight:800;margin-bottom:14px;display:flex;align-items:center;gap:8px"><i data-lucide="scale" class="icon" style="color:var(--saffron-dark)"></i> Potentially Relevant Provisions</h3>
            ${c.provisions.map(p => `
              <div class="provision" style="margin-bottom:12px">
                <h4><i data-lucide="scale" class="icon"></i> ${esc(p.offence_name)} — ${esc(p.section_number)}</h4>
                <p class="pv-offence">${esc(p.law_name)}</p>
                <p style="font-size:13.5px">${esc(p.matching_reason || '')}</p>
                <div class="pv-foot"><span class="relevance">${esc(p.relevance)} · ${p.confidence}%</span></div>
              </div>`).join('') || '<p class="small muted">No provisions were recorded.</p>'}
          </div>
          ${draft ? `<div class="card" style="padding:24px">
            <h3 style="font-size:16px;font-weight:800;margin-bottom:14px;display:flex;align-items:center;gap:8px"><i data-lucide="file-text" class="icon" style="color:var(--navy-800)"></i> FIR Draft</h3>
            <p class="small muted" style="margin-bottom:14px">Bilingual draft (English + ${esc(languageName(draft.regional_language))}) generated ${new Date(draft.created_at).toLocaleString('en-IN')}${draft.edited_by_user ? ' · edited by user' : ''}.</p>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <button class="btn btn-outline btn-sm" onclick="NV.loadDraft(${c.id})"><i data-lucide="external-link" class="icon"></i> Open Draft</button>
              <button class="btn btn-primary btn-sm" onclick="NV.downloadSavedPDF(${c.id})"><i data-lucide="download" class="icon"></i> Download PDF</button>
            </div></div>` : ''}
        </div>
        <div class="card" style="padding:24px;height:max-content">
          <h3 style="font-size:16px;font-weight:800;margin-bottom:16px;display:flex;align-items:center;gap:8px"><i data-lucide="history" class="icon" style="color:var(--blue-600)"></i> Processing History</h3>
          <div class="vtimeline">
            ${c.history.map(h => `<div class="vt-item"><div class="vt-dot"><i data-lucide="check" class="icon"></i></div>
              <div class="vt-body"><h5>${esc(h.event.replace(/_/g, ' '))}</h5><p class="vt-time">${new Date(h.created_at).toLocaleString('en-IN')}</p>
              ${h.detail ? `<p class="tiny muted">${esc(h.detail)}</p>` : ''}</div></div>`).join('')}
            <div class="vt-item"><div class="vt-dot" style="background:var(--blue-50);border-color:var(--blue-600)"><i data-lucide="clock" class="icon" style="color:var(--blue-600)"></i></div>
              <div class="vt-body"><h5>Officer Review</h5><p class="vt-time">${c.status === 'reviewed' ? 'Completed' : 'Pending'}</p></div></div>
          </div>
        </div>
      </div>`;
    icons();
  }

  async function markReviewed(id) {
    try {
      await api('/api/complaints/' + id, { method: 'PUT', body: JSON.stringify({ status: 'reviewed' }) });
      toast('Marked as reviewed');
      openComplaint(id);
    } catch (err) { toast(err.message); }
  }

  async function loadDraft(id) {
    try {
      const c = await api('/api/complaints/' + id);
      if (!c.draft) { toast('No draft stored for this complaint.'); return; }
      state.reference = c.reference_number;
      state.savedId = c.id;
      state.region = c.police_region;
      state.regionalLanguage = c.regional_language;
      state.firEdits = {};
      state.firBundle = {
        fir: c.draft.english_fir,
        field_labels: c.draft.field_labels || {},
        original_language: c.original_language,
        original_transcript: c.original_transcript,
        english_translation: c.english_translation,
        regional_language: c.regional_language,
      };
      state.regionalCopy = c.draft.regional_fir ? {
        fir: c.draft.regional_fir,
        labels: c.draft.regional_labels || {},
        language: c.regional_language,
        language_name: languageName(c.regional_language),
        translated: true,
      } : null;
      state.analysis = {
        original_transcript: c.original_transcript,
        english_translation: c.english_translation,
        original_language: c.original_language,
        classification: { label: c.crime_type, confidence: c.crime_confidence },
        provisions: [], entities: {}, summary: c.summary || '',
        incident_date_iso: c.incident_date_iso, law_regime: (c.analysis || {}).law_regime,
      };
      renderFIR();
      goStep(5);
    } catch (err) { toast(err.message); }
  }

  async function downloadSavedPDF(id) {
    await loadDraft(id);
    await downloadPDF();
  }

  // ------------------------------------------------------------- expose
  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

  return {
    showPage, goStep, newComplaint, toggleA11y, toggleSplit, toggleExplain, toast,
    pickLang, pickAuto, pickRegion, setMode, useTypedText, toggleRecording,
    resetRecording, hideError, runAnalysis, editEntity, showProvision, closeModal,
    generateFIR, regenerate, firTab, editFir, toggleEdit, saveComplaint, downloadPDF,
    loadDashboard, deleteComplaint, openComplaint, markReviewed, loadDraft, downloadSavedPDF,
  };
})();