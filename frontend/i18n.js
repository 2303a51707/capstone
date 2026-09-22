/* i18n.js - interface language switching for NyayaVoice.
 *
 * This translates the SHELL only: navigation, headings, buttons, labels.
 * It must never touch complaint content, transcripts, FIR fields or provision
 * text - those are translated by the backend translation service, which keeps
 * section numbers and amounts intact and records what it could not translate.
 * Anything inside [data-no-i18n] is left alone for exactly that reason.
 *
 * Strings are matched on their English text, so no markup changes are needed.
 * Anything without a translation stays in English rather than breaking.
 */
(function () {
  "use strict";

  const STRINGS = {
    hi: {
      // navigation
      "Home": "होम",
      "Report Incident": "घटना दर्ज करें",
      "Report an Incident": "घटना दर्ज करें",
      "How It Works": "यह कैसे काम करता है",
      "My Complaints": "मेरी शिकायतें",
      "About": "परिचय",
      // hero
      "Speak in Your Language.": "अपनी भाषा में बोलिए।",
      "Let NyayaVoice": "न्यायवॉइस को",
      "Understand.": "समझने दीजिए।",
      "Explore How It Works": "देखिए यह कैसे काम करता है",
      "Start Reporting": "शिकायत दर्ज करना शुरू करें",
      "Ready to listen…": "सुनने के लिए तैयार…",
      // pillars
      "Multilingual": "बहुभाषी",
      "Voice First": "आवाज़ पहले",
      "Legal Assistance": "कानूनी सहायता",
      "Privacy Focused": "गोपनीयता केंद्रित",
      "Language Access": "भाषा तक पहुँच",
      "Breaking the Language Barrier": "भाषा की दीवार तोड़ते हुए",
      // process
      "The Process": "प्रक्रिया",
      "Speak": "बोलिए",
      "Understand": "समझना",
      "Analyze": "विश्लेषण",
      "Find Relevant Provisions": "संबंधित धाराएँ खोजें",
      "Generate FIR": "एफ़आईआर तैयार करें",
      "Voice Input": "आवाज़ इनपुट",
      "Output": "परिणाम",
      "Police Station": "पुलिस थाना",
      "Citizen": "नागरिक",
      // review / analysis
      "Review the Translation": "अनुवाद की जाँच करें",
      "English Translation": "अंग्रेज़ी अनुवाद",
      "Original": "मूल",
      "Continue to Analysis": "विश्लेषण पर जाएँ",
      "Back": "पीछे",
      "Next": "आगे",
      "Potential provision": "संभावित धारा",
      "Rule layer": "नियम परत",
      "Statute retrieval": "धारा खोज",
      "Trained model": "प्रशिक्षित मॉडल",
      "Trained classifier": "प्रशिक्षित वर्गीकारक",
      "WHY IT MAY BE RELEVANT": "यह क्यों प्रासंगिक हो सकती है",
      "RELEVANT FACTS DETECTED": "पाए गए प्रासंगिक तथ्य",
      "View Details": "विवरण देखें",
      "Why did NyayaVoice suggest this?": "न्यायवॉइस ने यह क्यों सुझाया?",
      "High relevance": "उच्च प्रासंगिकता",
      "Medium relevance": "मध्यम प्रासंगिकता",
      "Low relevance": "निम्न प्रासंगिकता",
      // fir
      "Generate PDF": "पीडीएफ़ बनाएँ",
      "Download PDF": "पीडीएफ़ डाउनलोड करें",
      "Edit": "संपादित करें",
      "Save": "सहेजें",
      "Cancel": "रद्द करें",
      "Submit": "जमा करें",
      "Complainant Name": "शिकायतकर्ता का नाम",
      "Incident Date": "घटना की तिथि",
      "Incident Time": "घटना का समय",
      "Place of Occurrence": "घटना स्थल",
      "Reference Number": "संदर्भ संख्या",
      "Transparency &amp; Privacy": "पारदर्शिता और गोपनीयता",
      "Transparency & Privacy": "पारदर्शिता और गोपनीयता",
    },
    te: {
      "Home": "హోమ్",
      "Report Incident": "ఘటనను నమోదు చేయండి",
      "Report an Incident": "ఘటనను నమోదు చేయండి",
      "How It Works": "ఇది ఎలా పనిచేస్తుంది",
      "My Complaints": "నా ఫిర్యాదులు",
      "About": "గురించి",
      "Speak in Your Language.": "మీ భాషలో మాట్లాడండి.",
      "Let NyayaVoice": "న్యాయవాయిస్",
      "Understand.": "అర్థం చేసుకుంటుంది.",
      "Explore How It Works": "ఇది ఎలా పనిచేస్తుందో చూడండి",
      "Start Reporting": "ఫిర్యాదు ప్రారంభించండి",
      "Ready to listen…": "వినడానికి సిద్ధం…",
      "Multilingual": "బహుభాషా",
      "Voice First": "ముందుగా వాయిస్",
      "Legal Assistance": "న్యాయ సహాయం",
      "Privacy Focused": "గోప్యతకు ప్రాధాన్యం",
      "Language Access": "భాషా ప్రాప్యత",
      "Breaking the Language Barrier": "భాషా అడ్డంకిని అధిగమిస్తూ",
      "The Process": "ప్రక్రియ",
      "Speak": "మాట్లాడండి",
      "Understand": "అర్థం చేసుకోవడం",
      "Analyze": "విశ్లేషణ",
      "Find Relevant Provisions": "సంబంధిత సెక్షన్లను కనుగొనండి",
      "Generate FIR": "ఎఫ్‌ఐఆర్ రూపొందించండి",
      "Voice Input": "వాయిస్ ఇన్‌పుట్",
      "Output": "ఫలితం",
      "Police Station": "పోలీస్ స్టేషన్",
      "Citizen": "పౌరుడు",
      "Review the Translation": "అనువాదాన్ని సమీక్షించండి",
      "English Translation": "ఆంగ్ల అనువాదం",
      "Original": "అసలు",
      "Continue to Analysis": "విశ్లేషణకు కొనసాగండి",
      "Back": "వెనుకకు",
      "Next": "తదుపరి",
      "Potential provision": "సంభావ్య సెక్షన్",
      "Rule layer": "నియమ పొర",
      "Statute retrieval": "చట్ట అన్వేషణ",
      "Trained model": "శిక్షణ పొందిన మోడల్",
      "Trained classifier": "శిక్షణ పొందిన వర్గీకరణి",
      "WHY IT MAY BE RELEVANT": "ఇది ఎందుకు సంబంధితం కావచ్చు",
      "RELEVANT FACTS DETECTED": "గుర్తించిన సంబంధిత వాస్తవాలు",
      "View Details": "వివరాలు చూడండి",
      "Why did NyayaVoice suggest this?": "న్యాయవాయిస్ దీన్ని ఎందుకు సూచించింది?",
      "High relevance": "అధిక ప్రాసంగికత",
      "Medium relevance": "మధ్యస్థ ప్రాసంగికత",
      "Low relevance": "తక్కువ ప్రాసంగికత",
      "Generate PDF": "పీడీఎఫ్ రూపొందించండి",
      "Download PDF": "పీడీఎఫ్ డౌన్‌లోడ్ చేయండి",
      "Edit": "సవరించండి",
      "Save": "సేవ్ చేయండి",
      "Cancel": "రద్దు చేయండి",
      "Submit": "సమర్పించండి",
      "Complainant Name": "ఫిర్యాదుదారు పేరు",
      "Incident Date": "ఘటన తేదీ",
      "Incident Time": "ఘటన సమయం",
      "Place of Occurrence": "ఘటన జరిగిన ప్రదేశం",
      "Reference Number": "సూచన సంఖ్య",
      "Transparency &amp; Privacy": "పారదర్శకత మరియు గోప్యత",
      "Transparency & Privacy": "పారదర్శకత మరియు గోప్యత",
    },
  };

  // Content that belongs to the citizen or to the legal analysis is never
  // touched here. Inputs are excluded so typed text is never overwritten.
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "CODE", "PRE"]);
  const SKIP_SELECTOR = "[data-no-i18n]";

  const originals = new WeakMap();   // text node -> its English text
  let current = "en";

  function collect(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        if (SKIP_TAGS.has(parent.tagName)) return NodeFilter.FILTER_REJECT;
        if (parent.closest(SKIP_SELECTOR)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const out = [];
    let node;
    while ((node = walker.nextNode())) out.push(node);
    return out;
  }

  function apply(lang, root) {
    root = root || document.body;
    const table = STRINGS[lang] || null;
    for (const node of collect(root)) {
      if (!originals.has(node)) originals.set(node, node.nodeValue);
      const english = originals.get(node);
      const key = english.trim();
      if (!key) continue;
      if (!table) {                       // back to English
        node.nodeValue = english;
        continue;
      }
      const translated = table[key];
      // Untranslated strings stay in English rather than disappearing.
      if (translated) node.nodeValue = english.replace(key, translated);
      else node.nodeValue = english;
    }
    // Placeholders and titles live in attributes, not text nodes.
    root.querySelectorAll("[placeholder]").forEach((el) => {
      if (el.closest(SKIP_SELECTOR)) return;
      if (!el.dataset.i18nPlaceholder) el.dataset.i18nPlaceholder = el.placeholder;
      const src = el.dataset.i18nPlaceholder;
      el.placeholder = (table && table[src.trim()]) || src;
    });
    document.documentElement.lang = lang;
    current = lang;
    try { localStorage.setItem("nv-ui-lang", lang); } catch (e) { /* ignore */ }
  }

  const CODES = { "English": "en", "हिन्दी": "hi", "తెలుగు": "te",
                  "தமிழ்": "ta", "ಕನ್ನಡ": "kn", "മലയാളം": "ml" };

  function wire() {
    const select = document.querySelector(".lang-select");
    if (!select) return;
    select.addEventListener("change", () => {
      const code = CODES[select.value.trim()] || "en";
      if (!STRINGS[code] && code !== "en") {
        // Honest about coverage rather than silently doing nothing.
        if (window.NV && NV.toast) {
          NV.toast("Interface is available in English, हिन्दी and తెలుగు so far. "
                   + "Complaints can still be filed in every supported language.");
        }
        apply("en");
        select.value = "English";
        return;
      }
      apply(code);
    });

    let saved = "en";
    try { saved = localStorage.getItem("nv-ui-lang") || "en"; } catch (e) { /* ignore */ }
    if (saved !== "en" && STRINGS[saved]) {
      apply(saved);
      const label = Object.keys(CODES).find((k) => CODES[k] === saved);
      if (label) select.value = label;
    }
  }

  // Re-apply after the app renders a new page, so switching language on the
  // dashboard survives navigation.
  function refresh(root) { if (current !== "en") apply(current, root); }

  window.NV_I18N = { apply, refresh, current: () => current, strings: STRINGS };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
