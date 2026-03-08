export function syncTheme() {
  const saved = localStorage.getItem('theme');
  if (saved === 'light' || saved === 'dark') {
    document.documentElement.className = `theme-${saved}`;
  } else {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.className = `theme-${prefersDark ? 'dark' : 'light'}`;
  }
}
