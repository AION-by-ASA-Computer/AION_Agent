export type DateBucket =
  | "today"
  | "yesterday"
  | "previous_7_days"
  | "previous_30_days"
  | "older";

export const BUCKET_ORDER: DateBucket[] = [
  "today",
  "yesterday",
  "previous_7_days",
  "previous_30_days",
  "older",
];

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

export function bucketFor(timestamp: string | Date): DateBucket {
  const date = typeof timestamp === "string" ? new Date(timestamp) : timestamp;
  const today = startOfDay(new Date());
  const target = startOfDay(date);
  const diffDays = Math.round((today.getTime() - target.getTime()) / 86_400_000);
  if (diffDays <= 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays <= 7) return "previous_7_days";
  if (diffDays <= 30) return "previous_30_days";
  return "older";
}

export function groupByBucket<T extends { updated_at?: string | null }>(
  items: T[],
): Map<DateBucket, T[]> {
  const groups = new Map<DateBucket, T[]>();
  for (const item of items) {
    const bucket = item.updated_at ? bucketFor(item.updated_at) : "older";
    const list = groups.get(bucket) ?? [];
    list.push(item);
    groups.set(bucket, list);
  }
  return groups;
}
