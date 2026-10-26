export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || 'Something went wrong. Please try again.');
  }
  return response.json();
}

export function setHouseholdSession(household, memberId) {
  localStorage.setItem('homi:householdId', household.id);
  localStorage.setItem('homi:memberId', memberId || household.members[0]?.id || '');
}
