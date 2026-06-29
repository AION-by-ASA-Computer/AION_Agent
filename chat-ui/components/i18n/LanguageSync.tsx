"use client";

import { useEffect } from "react";
import { useT } from "@/lib/i18n/use-t";
import { getStoredToken } from "@/lib/auth/storage";
import { getLocale, initLocaleFromStorage } from "@/lib/i18n/i18n-store";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";

/**
 * LanguageSync — Componente invisibile che sincronizza l'attributo `lang` 
 * dell'elemento <html> con la lingua selezionata nello store.
 * Questo migliora l'accessibilità (screen reader) e permette ai motori 
 * di ricerca di identificare correttamente la lingua della pagina.
 */
export function LanguageSync() {
  // Ci sottoscriviamo allo store tramite useT (che internamente usa useSyncExternalStore)
  useT(); 

  useEffect(() => {
    const locale = getLocale();
    document.documentElement.lang = locale;
  }); // Eseguito ad ogni re-render innescato dal cambio lingua nello store

  // Sincronizza lingua e tema dal localStorage all'avvio per evitare reset da idratazione React
  useEffect(() => {
    // Inizializza lingua (localStorage o browser) post-idratazione
    initLocaleFromStorage();

    const token = getStoredToken();
    if (token) {
      void syncLanguagePreferenceToServer(token);
    }

    try {
      const stored = localStorage.getItem("aion-chat-theme");
      if (stored === "light" || stored === "dark") {
        document.documentElement.setAttribute("data-theme", stored);
      }
    } catch (e) {
      /* ignore */
    }
  }, []);

  return null;
}
