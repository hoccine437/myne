// modules/voice.js — voice OUTPUT. Server-authoritative.
//
// Default path: Zerion's response text is sent to the Core's Gemini TTS
// service over /ws ({"type":"tts", text, seq}); the server replies with
// a ready envelope carrying a one-time /api/tts/<token> WAV URL; the
// browser plays it (the phone's speaker IS the browser's speaker).
//
// The ONLY other voice path is browser speechSynthesis, used solely when
// the server reports fallback/unavailable — and it is always labeled
// BROWSER_TTS in the voice-state chip. It is never passed off as Gemini.
//
// States surfaced in the UI: GEMINI_TTS · GENERATING · BROWSER_TTS ·
// UNAVAILABLE · ERROR. Voice input (mic) lives in commandbar.js.

import { store } from "../core/store.js";
import { on, emit } from "../core/bus.js";
import { onSpeak } from "./chat.js";
import { core } from "../core/net.js";

let chip = null;
let state = "UNAVAILABLE";
let currentAudio = null;
let voices = [];
let amplitudeTimer = null;

export function available() { return true; } // server path always exists as a *request*

export function getVoices() { return voices; }

export function voiceState() { return state; }

function setState(next, note = "") {
  state = next;
  if (!chip) return;
  chip.dataset.vstate = next;
  chip.textContent = { GEMINI_TTS: "GEMINI VOICE", GENERATING: "VOICE…",
                       BROWSER_TTS: "BROWSER VOICE", UNAVAILABLE: "VOICE OFF",
                       ERROR: "VOICE ERROR" }[next] || next;
  chip.title = `voice path: ${next}${note ? " — " + note : ""}`;
}

/* ---------------- browser fallback (explicitly labeled) ---------------- */

function browserSpeak(text) {
  if (!("speechSynthesis" in window)) { setState("UNAVAILABLE"); return; }
  setState("BROWSER_TTS");
  voices = window.speechSynthesis.getVoices();
  const cleaned = String(text)
    .replace(/```[\s\S]*?```/g, " code block. ")
    .replace(/https?:\/\/\S+/g, " link ").replace(/[*_#>|-]{1,}/g, " ")
    .replace(/\s+/g, " ").trim().slice(0, 900);
  if (!cleaned) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(cleaned);
  const want = store.settings.voiceName;
  if (want) {
    const v = voices.find(v => v.voiceURI === want || v.name === want);
    if (v) u.voice = v;
  }
  u.rate = store.settings.voiceRate || 1;
  simulateAmplitude(u);
  window.speechSynthesis.speak(u);
}

function simulateAmplitude(utterance) {
  const orb = window.__zerionOrb;
  clearInterval(amplitudeTimer);
  if (utterance) {
    utterance.onstart = () => {
      amplitudeTimer = setInterval(() => orb?.setAmplitude(0.25 + Math.random() * 0.65), 110);
    };
    const stop = () => { clearInterval(amplitudeTimer); orb?.setAmplitude(0); };
    utterance.onend = stop;
    utterance.onerror = stop;
  }
}

function driveAmplitudePlayback(seconds) {
  const orb = window.__zerionOrb;
  const start = performance.now();
  clearInterval(amplitudeTimer);
  amplitudeTimer = setInterval(() => {
    if (performance.now() - start > seconds * 1000 + 400) {
      clearInterval(amplitudeTimer); orb?.setAmplitude(0); return;
    }
    orb?.setAmplitude(0.3 + Math.random() * 0.6);
  }, 110);
}

/* ---------------- server path ---------------- */

const pendingBySeq = new Map();

function serverSpeak(text, seq) {
  setState("GENERATING");
  pendingBySeq.set(seq ?? -1, { text, at: Date.now() });
  core.tts(text, seq);
}

on("core:tts", (d) => {
  const seq = typeof d.seq === "number" ? d.seq : -1;
  const pending = pendingBySeq.get(seq) || [...pendingBySeq.values()].pop();
  pendingBySeq.delete(seq);

  switch (d.state) {
    case "ready": {
      if (!d.url) { setState("ERROR", "empty audio url"); return; }
      setState("GEMINI_TTS", d.cached ? "served from Core cache" : "generated via Gemini TTS");
      try {
        currentAudio?.pause();
        const audio = new Audio(d.url);
        currentAudio = audio;
        audio.onplay = () => { store.core.state = "speaking"; };
        audio.onended = () => { orb_end(); };
        audio.onerror = () => { setState("ERROR", "audio could not be loaded"); };
        audio.play().catch(() => setState("ERROR", "playback blocked by browser"));
        driveAmplitudePlayback(10);
      } catch {
        setState("ERROR", "audio element unavailable");
      }
      break;
    }
    case "browser_fallback":
      browserSpeak(pending?.text || "");
      break;
    case "unavailable":
      setState("UNAVAILABLE", d.reason || "");
      emit("toast", { text: d.reason || "Voice is unavailable on this host.", level: "warning" });
      break;
    case "rate_limited":
      setState("ERROR", d.reason || "rate limited");
      browserSpeak(pending?.text || "");
      break;
    default:
      setState("ERROR", d.reason || "unknown TTS error");
  }
});

function orb_end() {
  const orb = window.__zerionOrb;
  clearInterval(amplitudeTimer);
  orb?.setAmplitude(0);
}

export function stopSpeaking() {
  try { window.speechSynthesis?.cancel(); } catch { }
  try { currentAudio?.pause(); } catch { }
  orb_end();
}

export function initVoice() {
  // state chip lives next to the mic button in the command bar
  const btn = document.getElementById("btn-voice");
  if (btn) {
    chip = document.createElement("span");
    chip.id = "voice-state-chip";
    chip.className = "voice-state-chip";
    btn.parentElement.insertBefore(chip, btn.nextSibling);
  }
  if ("speechSynthesis" in window) {
    voices = window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {
      voices = window.speechSynthesis.getVoices();
    };
  }

  const serverPath = store.core.serverSettings?.voice_path;
  setState(store.settings.voiceOutput
           ? (serverPath === "server-gemini" ? "GEMINI_TTS" : "BROWSER_TTS")
           : "UNAVAILABLE");

  on("hello", (d) => {
    if (!store.settings.voiceOutput) { setState("UNAVAILABLE"); return; }
    const path = d.settings?.voice_path;
    setState(path === "server-gemini" ? "GEMINI_TTS" : "BROWSER_TTS",
             path === "server-gemini" ? "ready" : "server TTS not ready");
  });

  onSpeak((text, seq) => {
    if (!store.settings.voiceOutput) return;
    serverSpeak(text, seq);
  });

  on("connection", ({ connected }) => { if (!connected) stopSpeaking(); });
}
