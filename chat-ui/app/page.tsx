"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Loader2 } from "lucide-react";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    const id = crypto.randomUUID();
    router.replace(`/c/${id}`);
  }, [router]);
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background text-muted-foreground">
      <Loader2 className="animate-spin text-primary" size={22} aria-hidden />
      <span className="text-sm">Nuova conversazione…</span>
    </div>
  );
}
