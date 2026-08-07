// modules/voice.js — voice OUTPUT for the web client (browser TTS).
//
// The Core's own speech module renders to a server-side audio player —
// correct for the terminal, invisible to a remote browser. The web UI
// therefore performs presentation-layer TTS via speechSynthesis,
// honoring the client's voice settings. Voice INPUT lives in
// commandbar.js (SpeechRecognition).

import { store } from "../core/store.js";
import { on } from "../core/bus.js";
import { onSpeak } from "./chat.js";

let voices = [];
let amplitudeTimer = null;

export function available() { return "speechSynthesis" in window; }

export function getVoices() { return voices; }

function refreshVoices() {
  voices = window.speechSynthesis?.getVoices?.() || [];
  return voices;
}

function cleanForSpeech(text) {
  return String(text)
    .replace(/```[\s\S]*?```/g, " code block. ")
    .replace(/`[^`]+`/g, " code ")
    .replace(/\[Attached file:[^\]]+\]/g, "")
    .replace(/https?:\/\/\S+/g, " link ")
    .replace(/[*_#>|-]{1,}/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 900);
}

function simulateAmplitude(utterance) {
  // drive the orb's speaking waveform while TTS runs
  const orb = window.__zerionOrb;
  clearInterval(amplitudeTimer);
  utterance.onstart = () => {
    amplitudeTimer = setInterval(() => {
      orb?.setAmplitude(0.25 + Math.random() * 0.65);
    }, 110);
  };
  const stop = () => { clearInterval(amplitudeTimer); orb?.setAmplitude(0); };
  utterance.onend = stop;
  utterance.onerror = stop;
}

function speak(text) {
  if (!available() || !store.settings.voiceOutput) return;
  const cleaned = cleanForSpeech(text);
  if (!cleaned) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(cleaned);
  const want = store.settings.voiceName;
  if (want) {
    const v = voices.find(v => v.voiceURI === want || v.name === want);
    if (v) u.voice = v;
  }
  u.rate = store.settings.voiceRate || 1;
  u.lang = u.voice?.lang || ({ en: "en-US", fr: "fr-FR", es: "es-ES", de: "de-DE" })[store.settings.language] || "en-US";
  simulateAmplitude(u);
  window.speechSynthesis.speak(u);
}

export function stopSpeaking() {
  try { window.speechSynthesis?.cancel(); } catch { }
}

export function initVoice() {
  if (!available()) return;
  refreshVoices();
  window.speechSynthesis.onvoiceschanged = refreshVoices;
  onSpeak(speak);
  on("connection", ({ connected }) => { if (!connected) stopSpeaking(); });
}
