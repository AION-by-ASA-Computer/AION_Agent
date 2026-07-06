import { MainShell } from "@/components/layout/MainShell";

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  return <MainShell>{children}</MainShell>;
}
