// modules/i18n.js — UI chrome translations (AI responses are untouched;
// they come from the Core). Dictionaries cover interface labels only.

import { store } from "../core/store.js";

const DICTS = {
  en: {
    systemStatus: "System Status", activeAgents: "Active Agents", currentGoal: "Current Goal",
    activeTasks: "Active Tasks", runningTools: "Running Tools", recentDecisions: "Recent Decisions",
    notifications: "Notifications", memory: "Memory", uptime: "Uptime", explorer: "File Explorer",
    askZerion: "Ask Zerion anything — or type / for commands", noTasks: "No running plan.", idle: "Idle.",
  },
  fr: {
    systemStatus: "État système", activeAgents: "Agents actifs", currentGoal: "Objectif actuel",
    activeTasks: "Tâches actives", runningTools: "Outils en cours", recentDecisions: "Décisions récentes",
    notifications: "Notifications", memory: "Mémoire", uptime: "Disponibilité", explorer: "Explorateur de fichiers",
    askZerion: "Demandez à Zerion — ou tapez / pour les commandes", noTasks: "Aucun plan en cours.", idle: "Inactif.",
  },
  es: {
    systemStatus: "Estado del sistema", activeAgents: "Agentes activos", currentGoal: "Objetivo actual",
    activeTasks: "Tareas activas", runningTools: "Herramientas activas", recentDecisions: "Decisiones recientes",
    notifications: "Notificaciones", memory: "Memoria", uptime: "Tiempo activo", explorer: "Explorador de archivos",
    askZerion: "Pregunta a Zerion — o escribe / para comandos", noTasks: "Sin plan en curso.", idle: "Inactivo.",
  },
  de: {
    systemStatus: "Systemstatus", activeAgents: "Aktive Agenten", currentGoal: "Aktuelles Ziel",
    activeTasks: "Aktive Aufgaben", runningTools: "Laufende Werkzeuge", recentDecisions: "Letzte Entscheidungen",
    notifications: "Hinweise", memory: "Speicher", uptime: "Laufzeit", explorer: "Datei-Explorer",
    askZerion: "Frag Zerion — oder tippe / für Befehle", noTasks: "Kein aktiver Plan.", idle: "Leerlauf.",
  },
};

export function t(key) {
  const lang = store.settings.language;
  return DICTS[lang]?.[key] || DICTS.en[key] || key;
}

export function applyI18n() {
  const lang = store.settings.language;
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-title]").forEach(el => { el.title = t(el.dataset.i18nTitle); });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
}
