export function query(
  params: Record<string, string | number | boolean | null | undefined>,
) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}
