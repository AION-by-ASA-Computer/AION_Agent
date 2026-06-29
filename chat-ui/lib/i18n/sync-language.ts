import { apiBase } from "@/lib/config";
import { getLocale, type Locale } from "@/lib/i18n/i18n-store";

/** Persist current UI locale to ``users.metadata_json.language`` via PATCH /auth/me. */
export async function syncLanguagePreferenceToServer(
  token: string,
  lang?: Locale
): Promise<boolean> {
  const locale = lang ?? getLocale();
  try {
    const res = await fetch(`${apiBase()}/auth/me`, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ metadata: { language: locale } }),
    });
    return res.ok;
  } catch {
    return false;
  }
}
