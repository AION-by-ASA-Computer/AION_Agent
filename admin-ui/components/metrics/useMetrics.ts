"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import type { MetricsOverviewData, ProfileItem, TimeRange, UserItem } from "./types";

const POLL_MS = 3000;

/** Overview metrics for the chosen scope, plus the profile and user lists that feed the filters. */
export function useMetrics() {
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [profile, setProfileRaw] = useState("");
  const [user, setUserRaw] = useState("");
  const [range, setRangeRaw] = useState<TimeRange>("1h");
  const [live, setLive] = useState(true);
  const [metrics, setMetrics] = useState<MetricsOverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    apiFetch(`${apiBase()}/admin/profiles`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => Array.isArray(d) && setProfiles(d))
      .catch(() => {});
    apiFetch(`${apiBase()}/admin/users`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => d && Array.isArray(d.users) && setUsers(d.users))
      .catch(() => {});
  }, []);

  const load = useCallback(() => {
    const id = ++seq.current;
    const q = new URLSearchParams({ time_range: range });
    if (profile) q.set("profile", profile);
    if (user) q.set("user_id", user);
    apiFetch(`${apiBase()}/admin/metrics/overview?${q}`)
      .then((res) => (res.ok ? (res.json() as Promise<MetricsOverviewData>) : Promise.reject(res)))
      .then((data) => {
        if (id !== seq.current) return; // a newer scope superseded this response
        setMetrics(data);
        setFailed(false);
        setUpdatedAt(new Date());
      })
      .catch(() => id === seq.current && setFailed(true))
      .finally(() => id === seq.current && setLoading(false));
  }, [profile, user, range]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => load(), POLL_MS);
    return () => clearInterval(timer);
  }, [live, load]);

  // A changed scope shows the loading state straight away; background polls stay silent.
  const scoped = <V,>(set: (v: V) => void) => (v: V) => {
    setLoading(true);
    set(v);
  };
  const reload = () => {
    setLoading(true);
    load();
  };

  return { profiles, users, profile, setProfile: scoped(setProfileRaw), user, setUser: scoped(setUserRaw), range, setRange: scoped(setRangeRaw), live, setLive, metrics, loading, failed, updatedAt, reload };
}
