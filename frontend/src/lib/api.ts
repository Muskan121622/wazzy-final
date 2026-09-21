import axios, { AxiosInstance } from 'axios';

// ─────────────────────────────────────────────────────────────
// Wayzyy TripOS API client (production-aware)
//  • Auto-switch local vs Render backend
//  • Manages auth token + active trip id transparently (localStorage)
//  • Remaps legacy 'trip_1' calls to the real per-user trip
// ─────────────────────────────────────────────────────────────

const RENDER_API_BASE = 'https://wazzy.onrender.com/api';
const LOCAL_API_BASE = 'http://localhost:8000/api';

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== 'undefined' && ['localhost', '127.0.0.1'].includes(window.location.hostname)
    ? LOCAL_API_BASE
    : RENDER_API_BASE);

const TOKEN_KEY = 'hiver_token';
const TRIP_KEY = 'hiver_trip_id';

// Demo account seeded by backend/database/seed.py. Real users can register/login.
const DEMO_LOGIN = { email: 'demo@wayzyy.app', password: 'demo1234' };

const http: AxiosInstance = axios.create({ baseURL: API_BASE });

http.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

const isLocal = typeof window !== 'undefined';
const getStore = (k: string) => (isLocal ? localStorage.getItem(k) : null);
const setStore = (k: string, v: string) => { if (isLocal) localStorage.setItem(k, v); };
const clearStore = (k: string) => { if (isLocal) localStorage.removeItem(k); };

let sessionPromise: Promise<void> | null = null;

// Ensure we have a token + a resolved active trip before making scoped calls.
async function ensureSession(): Promise<void> {
  if (sessionPromise) return sessionPromise;
  sessionPromise = (async () => {
    try {
      if (!getStore(TOKEN_KEY)) {
        // Try the seeded demo account first (owns the rich trip_1 sample data),
        // then fall back to an ephemeral guest.
        let res;
        try {
          res = await http.post('/auth/login', DEMO_LOGIN);
        } catch {
          res = await http.post('/auth/guest', { name: 'Guest Traveler' });
        }
        setStore(TOKEN_KEY, res.data.token);
      }
      // Resolve the user's most recent trip if we don't already have one.
      if (!getStore(TRIP_KEY)) {
        const list = await http.get('/trip');
        const trips = list.data?.trips || [];
        if (trips.length) setStore(TRIP_KEY, trips[0].id);
      }
    } catch (e) {
      sessionPromise = null; // allow retry next call
      console.error('TripOS session bootstrap failed', e);
    }
  })();
  return sessionPromise;
}

function activeTripId(fallback?: string): string {
  const stored = getStore(TRIP_KEY);
  // Treat the legacy hardcoded 'trip_1' as "use whatever the user actually owns".
  if (!fallback || fallback === 'trip_1') return stored || 'trip_1';
  return fallback;
}

export const auth = {
  async register(name: string, email: string, password: string) {
    const res = await http.post('/auth/register', { name, email, password });
    setStore(TOKEN_KEY, res.data.token);
    clearStore(TRIP_KEY);
    return res.data;
  },
  async login(email: string, password: string) {
    const res = await http.post('/auth/login', { email, password });
    setStore(TOKEN_KEY, res.data.token);
    clearStore(TRIP_KEY);
    return res.data;
  },
  async guest() {
    const res = await http.post('/auth/guest', { name: 'Guest Traveler' });
    setStore(TOKEN_KEY, res.data.token);
    clearStore(TRIP_KEY);
    return res.data;
  },
  logout() {
    clearStore(TOKEN_KEY);
    clearStore(TRIP_KEY);
  },
  me: async () => (await http.get('/auth/me')).data,
};

export const api = {
  getTrip: async (tripId?: string) => {
    await ensureSession();
    const res = await http.get(`/trip/${activeTripId(tripId)}`);
    return res.data;
  },

  updatePreferences: async (pref: {
    quietness: number;
    seafood: number;
    budget_max: number;
    crowd_tolerance: number;
    energy_level: string;
  }) => {
    await ensureSession();
    const res = await http.post('/trip/preferences', pref);
    return res.data;
  },

  generateTrip: async (data: {
    user_name?: string;
    destination: string;
    days_count: number;
    quietness: number;
    seafood: number;
    total_budget?: number;
    budget_max?: number;
    crowd_tolerance: number;
    energy_level: string;
    start_date?: string;
    end_date?: string;
    dest_lat?: number;
    dest_lon?: number;
  }) => {
    await ensureSession();
    const res = await http.post('/trip/generate', data);
    if (res.data?.trip_id) setStore(TRIP_KEY, res.data.trip_id);
    return res.data;
  },

  triggerIncident: async (tripId?: string, _condition?: string, dayNumber: number = 1, _timeSlot?: string) => {
    await ensureSession();
    const res = await http.post('/incident/trigger', { trip_id: activeTripId(tripId), day_number: dayNumber });
    return res.data;
  },

  checkClosed: async (tripId?: string, dayNumber: number = 1) => {
    await ensureSession();
    const res = await http.post('/incident/check-closed', { trip_id: activeTripId(tripId), day_number: dayNumber });
    return res.data;
  },

  evaluateDelay: async (
    tripId?: string,
    dayNumber: number = 1,
    delayMinutes: number = 45,
    userLat?: number,
    userLon?: number,
    speedKmh: number = 25.0
  ) => {
    await ensureSession();
    // Live mode: when we have a GPS fix, send the traveller's current local
    // time and drop the estimated delay — the backend derives lateness from
    // "now + travel time from GPS" instead of a fixed constant.
    const hasGps = typeof userLat === 'number' && typeof userLon === 'number';
    const now = new Date();
    const current_time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    const res = await http.post('/incident/evaluate-delay', {
      trip_id: activeTripId(tripId),
      day_number: dayNumber,
      delay_minutes: hasGps ? 0 : delayMinutes,
      user_lat: userLat,
      user_lon: userLon,
      speed_kmh: speedKmh,
      current_time,
    });
    return res.data;
  },

  getProposals: async (tripId?: string) => {
    await ensureSession();
    const res = await http.get('/incident/proposals', { params: { trip_id: activeTripId(tripId) } });
    return res.data;
  },

  approveProposal: async (proposalId: string, _tripId?: string) => {
    await ensureSession();
    const res = await http.post('/incident/approve', { proposal_id: proposalId });
    return res.data;
  },

  rejectProposal: async (proposalId: string) => {
    await ensureSession();
    const res = await http.post('/incident/reject', { proposal_id: proposalId });
    return res.data;
  },

  getRightNow: async (tripId?: string, isRainy: boolean = false) => {
    await ensureSession();
    const res = await http.get('/incident/right-now', { params: { trip_id: activeTripId(tripId), is_rainy: isRainy } });
    return res.data;
  },

  addActivity: async (placeId: string, dayNumber: number, tripId?: string, timeSlot?: string) => {
    await ensureSession();
    const res = await http.post('/trip/add-activity', {
      trip_id: activeTripId(tripId),
      place_id: placeId,
      day_number: dayNumber,
      time_slot: timeSlot || null,
    });
    return res.data;
  },

  getHostTips: async (tripId?: string) => {
    await ensureSession();
    const res = await http.get('/incident/host-tips', { params: { trip_id: activeTripId(tripId) } });
    return res.data;
  },

  chatWithAgent: async (
    userMessage: string,
    tripId?: string,
    destination?: string,
    history?: { role: string; content: string }[]
  ) => {
    await ensureSession();
    const res = await http.post('/chat', {
      user_message: userMessage,
      trip_id: activeTripId(tripId),
      destination: destination || null,
      history: history || [],
    });
    return res.data;
  },
};

export { API_BASE };
