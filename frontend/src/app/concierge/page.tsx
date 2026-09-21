'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import GoogleTranslate from '@/components/GoogleTranslate';
import {
  Sparkles, CloudRain, Clock, Home, Shield, Activity, Send, Zap,
  CheckCircle2, AlertTriangle, Info, MapPin, Utensils, Sun, Coffee,
  Building2, ChevronRight, RefreshCw, Cpu, X, Plus, Check, Percent,
  Compass, Car, Navigation, Bell, Mic, MicOff, ArrowRight, Star,
  CloudSun, ThumbsUp, RotateCcw, Layers
} from 'lucide-react';
import { api } from '@/lib/api';

// ─── Animation Variants ───────────────────────────────────────────────────────
const fadeUp = { hidden: { opacity: 0, y: 20 }, show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: 'easeOut' as const } } };
const slideIn = { hidden: { opacity: 0, x: -16 }, show: { opacity: 1, x: 0, transition: { duration: 0.4, ease: 'easeOut' as const } } };
const cardHover = {
  rest: { y: 0 },
  hover: { y: -3, transition: { duration: 0.25, ease: 'easeOut' as const } },
};

export default function ConciergePage() {
  // ─── All existing state (unchanged) ─────────────────────────────────────────
  const [tripData, setTripData] = useState<any>(null);
  const [activeDay, setActiveDay] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(true);

  const [showRightNow, setShowRightNow] = useState<boolean>(false);
  const [rightNowCandidates, setRightNowCandidates] = useState<any[]>([]);
  const [addedCandidates, setAddedCandidates] = useState<Record<number, boolean>>({});

  const [showHostTips, setShowHostTips] = useState<boolean>(false);
  const [hostTips, setHostTips] = useState<any[]>([]);

  const [showArchitecture, setShowArchitecture] = useState<boolean>(false);
  const [showNotifications, setShowNotifications] = useState<boolean>(false);
  const [isChatOpen, setIsChatOpen] = useState<boolean>(false);

  const [incidentResult, setIncidentResult] = useState<any>(null);
  const [showIncidentToast, setShowIncidentToast] = useState<boolean>(false);

  const [delayResult, setDelayResult] = useState<any>(null);
  const [showDelayModal, setShowDelayModal] = useState<boolean>(false);

  const [travelerName, setTravelerName] = useState<string>('Muskan');
  const [tripDestination, setTripDestination] = useState<string>('Goa');

  const [chatMessages, setChatMessages] = useState<any[]>([{
    sender: 'agent',
    text: "👋 Hi Muskan! Welcome to Wayzyy TripOS. Your living itinerary is active and synced with Superhosts Rahul & Priya. I use OpenStreetMap GIS spatial searching, live weather monitoring, and host recommendations to manage your trip. How can I assist you today?",
    tool: null,
  }]);
  const [inputMsg, setInputMsg] = useState<string>('');
  const [chatLoading, setChatLoading] = useState<boolean>(false);
  const [isListening, setIsListening] = useState<boolean>(false);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  // ─── Voice Input (unchanged) ─────────────────────────────────────────────────
  const startVoiceInput = () => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) { alert('Voice input is not supported in this browser. Please use Chrome or Edge.'); return; }
    const recognition = new SpeechRecognition();
    recognition.lang = 'en-IN';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    setIsListening(true);
    recognition.start();
    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setInputMsg(transcript);
      setIsListening(false);
      setTimeout(() => handleSendMessage(transcript), 600);
    };
    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);
  };

  // ─── fetchTrip (unchanged) ───────────────────────────────────────────────────
  const fetchTrip = async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      const data = await api.getTrip('trip_1');
      setTripData(data);
    } catch (err) {
      console.error('Failed to load trip', err);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // ─── Init (unchanged) ────────────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storedName = localStorage.getItem('wayzyy_user_name');
      const storedDest = localStorage.getItem('wayzyy_destination');
      if (storedName) {
        setTravelerName(storedName);
        setChatMessages([{
          sender: 'agent',
          text: `👋 Hi ${storedName}! Welcome to Wayzyy TripOS. Your living itinerary for **${storedDest || 'Goa'}** is active and synced with Superhosts Rahul & Priya. I use OpenStreetMap GIS spatial searching, live weather monitoring, and host recommendations to manage your trip. How can I assist you today?`,
          tool: null,
        }]);
      }
      if (storedDest) setTripDestination(storedDest);
    }
    fetchTrip();
  }, []);

  // Scroll chat to bottom
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, chatLoading]);

  // ─── Incident Trigger (unchanged) ────────────────────────────────────────────
  const handleTriggerIncident = async () => {
    try {
      const res = await api.triggerIncident('trip_1', 'HEAVY_RAIN', activeDay, '02:00 PM');
      if (res.status === 'PROPOSAL_CREATED' && res.swapped_details?.length > 0) {
        await api.approveProposal(res.swapped_details[0].proposal_id, 'trip_1');
        res.auto_applied = true;
        setIncidentResult(res);
        setShowIncidentToast(true);
        fetchTrip();
      } else {
        setIncidentResult(res);
        setShowIncidentToast(true);
      }
    } catch (err) { console.error('Incident trigger failed', err); }
  };

  // ─── Delay Evaluation (unchanged) ────────────────────────────────────────────
  const handleEvaluateDelay = async () => {
    try {
      const now = new Date();
      const hourOfDay = now.getHours();
      const dynamicDelay = hourOfDay >= 17 ? 60 : hourOfDay >= 12 ? 45 : 20;
      const getGPS = (): Promise<{ lat: number; lon: number }> =>
        new Promise((resolve) => {
          if (!navigator.geolocation) { resolve({ lat: 15.5057, lon: 73.9269 }); return; }
          navigator.geolocation.getCurrentPosition(
            (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
            () => { console.warn('GPS denied — using destination fallback'); resolve({ lat: 15.5057, lon: 73.9269 }); },
            { timeout: 6000, maximumAge: 30000 }
          );
        });
      const { lat, lon } = await getGPS();
      const res = await api.evaluateDelay('trip_1', activeDay, dynamicDelay, lat, lon, 25.0);
      if (res.status === 'CONFLICT_DETECTED' && res.proposal?.proposal_id) {
        await api.approveProposal(res.proposal.proposal_id, 'trip_1');
        res.auto_applied = true;
        setDelayResult(res);
        setShowDelayModal(true);
        fetchTrip();
      } else {
        setDelayResult(res);
        setShowDelayModal(true);
      }
    } catch (err) { console.error('Delay evaluation failed', err); }
  };

  // ─── Accept Recovery (unchanged) ─────────────────────────────────────────────
  const handleAcceptRecovery = async (proposalId?: string) => {
    try {
      const targetId = proposalId || (incidentResult?.swapped_details?.[0]?.proposal_id);
      if (targetId) await api.approveProposal(targetId, 'trip_1');
      setShowIncidentToast(false);
      setShowDelayModal(false);
      fetchTrip();
    } catch (err) { console.error('Failed to approve proposal', err); }
  };

  // ─── Right Now (unchanged) ───────────────────────────────────────────────────
  const handleFetchRightNow = async () => {
    try {
      const res = await api.getRightNow('trip_1', false);
      setRightNowCandidates(res.candidates || []);
      setShowRightNow(true);
    } catch (err) { console.error('Right now failed', err); }
  };

  // ─── Add a right-now recommendation to the currently-viewed day ───────────────
  const handleAddRecommendation = async (c: any, idx: number) => {
    const placeId = c.place?.id || c.place_id || c.id;
    if (!placeId || addedCandidates[idx]) return;
    try {
      const res = await api.addActivity(placeId, activeDay, 'trip_1');
      if (res?.status === 'SUCCESS') {
        setAddedCandidates((prev) => ({ ...prev, [idx]: true }));
        await fetchTrip(true);
        setTimeout(() => {
          setAddedCandidates((prev) => { const n = { ...prev }; delete n[idx]; return n; });
        }, 2600);
      } else {
        console.error('Add activity rejected', res);
      }
    } catch (err) { console.error('Add activity failed', err); }
  };

  // ─── Host Tips (unchanged) ───────────────────────────────────────────────────
  const handleFetchHostTips = async () => {
    try {
      const res = await api.getHostTips('trip_1');
      setHostTips(res.host_tips || []);
      setShowHostTips(true);
    } catch (err) { console.error('Host tips failed', err); }
  };

  // ─── Chat (unchanged) ────────────────────────────────────────────────────────
  const handleSendMessage = async (customMsg?: string) => {
    const msgToSend = customMsg || inputMsg;
    if (!msgToSend.trim()) return;
    const newUserMsg = { sender: 'user', text: msgToSend };
    setChatMessages((prev) => [...prev, newUserMsg]);
    if (!customMsg) setInputMsg('');
    setChatLoading(true);
    try {
      const historyForApi = chatMessages
        .filter((m) => m.sender === 'user' || m.sender === 'agent')
        .slice(-10)
        .map((m) => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text }));
      const res = await api.chatWithAgent(msgToSend, 'trip_1', tripDestination, historyForApi);
      setChatMessages((prev) => [...prev, {
        sender: 'agent',
        text: res.reply,
        tool: res.tool_executed ? { name: res.tool_executed, args: res.tool_args } : null,
      }]);
      fetchTrip(true);
    } catch (err) {
      setChatMessages((prev) => [...prev, { sender: 'agent', text: 'Error connecting to TripOS Agent.', tool: null }]);
    } finally { setChatLoading(false); }
  };

  // ─── Loading State ───────────────────────────────────────────────────────────
  if (loading || !tripData) {
    return (
      <div className="min-h-screen bg-[#050B14] flex items-center justify-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center"
        >
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5 relative"
            style={{ background: 'rgba(255,107,53,0.1)', border: '1px solid rgba(255,107,53,0.25)' }}>
            <RefreshCw className="w-7 h-7 text-orange-400 animate-spin" />
            <div className="absolute inset-0 rounded-2xl animate-ping opacity-30"
              style={{ background: 'rgba(255,107,53,0.1)' }} />
          </div>
          <p className="text-white font-semibold text-sm" style={{ fontFamily: 'var(--font-sora)' }}>Initializing Wayzyy TripOS Engine...</p>
          <p className="text-slate-500 text-xs mt-1">Syncing GIS data & live itinerary</p>
        </motion.div>
      </div>
    );
  }

  const { trip, preferences, itinerary_days, versions } = tripData;
  const timeOrder: Record<string, number> = { Morning: 1, Afternoon: 2, Evening: 3 };
  const rawItems = itinerary_days[activeDay] || [];
  const currentDayItems = [...rawItems].sort((a: any, b: any) => {
    const pA = timeOrder[a.time_period] || 4;
    const pB = timeOrder[b.time_period] || 4;
    return pA - pB;
  });

  // ─── RENDER ──────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[#050B14] text-slate-100 font-sans selection:bg-orange-500/30 selection:text-white">

      {/* ══ FULL PAGE BACKGROUND (bright beach, same as front page) ═══════════ */}
      <div className="fixed inset-0 z-0 pointer-events-none">
        <img
          src="https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?w=1600&q=85"
          alt="Goa beach"
          className="w-full h-full object-cover object-center opacity-100"
        />
        {/* Soft left gradient for text readability */}
        <div className="absolute inset-0" style={{
          background: 'linear-gradient(90deg, rgba(5,11,20,0.7) 0%, rgba(5,11,20,0.1) 45%, transparent 100%)',
        }} />
        {/* Soft bottom gradient for card contrast */}
        <div className="absolute inset-0" style={{
          background: 'linear-gradient(to top, rgba(5,11,20,0.85) 0%, rgba(5,11,20,0.2) 40%, transparent 100%)',
        }} />
      </div>

      {/* ══ HEADER ═════════════════════════════════════════════════════════════ */}
      <header className="sticky top-0 z-40 border-b border-white/8"
        style={{ background: 'rgba(5,11,20,0.88)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)' }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-[64px] flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link href="/" className="flex items-center gap-2.5 shrink-0">
              <div className="w-8 h-8 rounded-xl flex items-center justify-center font-black text-[#050B14] text-base"
                style={{ background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)', boxShadow: '0 3px 12px rgba(255,107,53,0.4)' }}>
                W
              </div>
              <span className="font-bold text-lg text-white tracking-tight hidden sm:block" style={{ fontFamily: 'var(--font-sora)' }}>
                Wayzyy <span style={{ color: '#FF6B35' }}>TripOS</span>
              </span>
            </Link>
            <span className="hidden md:flex items-center gap-1.5 text-[11px] font-medium px-3 py-1.5 rounded-full shrink-0"
              style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.09)', color: '#94A3B8' }}>
              <MapPin className="w-3 h-3 text-orange-400" />
              {trip.destination || 'Goa'} · OSM GIS
            </span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span className="hidden md:flex text-[11px] font-bold px-2.5 py-1 rounded-full"
              style={{ background: 'rgba(255,107,53,0.1)', border: '1px solid rgba(255,107,53,0.25)', color: '#FF8A65' }}>
              v{trip.current_version} ⚡ Living
            </span>
            <GoogleTranslate />
            <Link href="/" className="hidden sm:flex px-3 py-1.5 text-[11px] font-bold rounded-full items-center gap-1.5 text-white transition-all"
              style={{ background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)', boxShadow: '0 3px 12px rgba(255,107,53,0.3)' }}>
              <Sparkles className="w-3 h-3" /> New Trip
            </Link>
            <button onClick={() => setShowArchitecture(true)}
              className="hidden sm:flex px-3 py-1.5 text-[11px] font-bold rounded-full items-center gap-1.5 text-slate-300 transition-all"
              style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.09)' }}>
              <Cpu className="w-3 h-3 text-teal-400" /> Architecture
            </button>

            {/* Notifications */}
            <div className="relative">
              <button onClick={() => setShowNotifications(!showNotifications)}
                className="relative p-2 rounded-xl transition-colors"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.09)' }}>
                <Bell className="w-4 h-4 text-slate-300" />
                {tripData.audit_actions?.length > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-rose-500 rounded-full border-2 border-[#050B14] animate-pulse" />
                )}
              </button>
              <AnimatePresence>
                {showNotifications && (
                  <motion.div
                    initial={{ opacity: 0, y: -8, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -8, scale: 0.96 }}
                    transition={{ duration: 0.2 }}
                    className="absolute right-0 mt-2 w-80 rounded-2xl shadow-2xl z-50 overflow-hidden"
                    style={{ background: 'rgba(7,17,31,0.98)', border: '1px solid rgba(255,255,255,0.1)', backdropFilter: 'blur(20px)' }}
                  >
                    <div className="px-4 py-3 border-b border-white/6 flex justify-between items-center"
                      style={{ background: 'rgba(255,255,255,0.03)' }}>
                      <h4 className="font-bold text-white text-sm">Trip Notifications</h4>
                      <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                        style={{ background: 'rgba(255,107,53,0.15)', color: '#FF8A65' }}>
                        {tripData.audit_actions?.length || 0} New
                      </span>
                    </div>
                    <div className="max-h-72 overflow-y-auto divide-y divide-white/5">
                      {!tripData.audit_actions?.length ? (
                        <p className="text-xs text-slate-500 p-4 text-center">No recent notifications.</p>
                      ) : tripData.audit_actions?.map((action: any, idx: number) => (
                        <div key={idx} className="p-3.5 flex items-start gap-3 hover:bg-white/3 transition-colors">
                          <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0"
                            style={{ background: action.action === 'TRIP_INSIGHT' ? 'rgba(99,102,241,0.15)' : 'rgba(255,107,53,0.12)' }}>
                            {action.action === 'TRIP_INSIGHT'
                              ? <Cpu className="w-3.5 h-3.5 text-indigo-400" />
                              : <Zap className="w-3.5 h-3.5 text-orange-400" />}
                          </div>
                          <div>
                            <span className="text-[10px] font-bold block mb-0.5" style={{ color: '#FF8A65' }}>
                              {action.action.replace(/_/g, ' ')}
                            </span>
                            <p className="text-xs text-slate-300 leading-relaxed">{action.reason}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </header>

      {/* ══ DEMO TRIGGER BAR ═══════════════════════════════════════════════════ */}
      <div className="relative z-10 border-b border-white/6"
        style={{ background: 'rgba(5,11,20,0.35)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)' }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold text-orange-400 uppercase tracking-widest">Demo Triggers</span>
            <span className="text-[11px] text-slate-500">· Click to test TripOS Engines live</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {[
              { label: 'Rain Incident (2 PM)', onClick: handleTriggerIncident, rgb: '244,63,94', textColor: '#FDA4AF', icon: CloudRain },
              { label: 'Traffic Delay (d/v Matrix)', onClick: handleEvaluateDelay, rgb: '99,102,241', textColor: '#A5B4FC', icon: Car },
              { label: 'What to do right now?', onClick: handleFetchRightNow, rgb: '245,158,11', textColor: '#FCD34D', icon: Zap },
              { label: 'Direct Host Tips', onClick: handleFetchHostTips, rgb: '20,184,166', textColor: '#5EEAD4', icon: Home },
            ].map(({ label, onClick, rgb, textColor, icon: Icon }) => (
              <motion.button
                key={label}
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                onClick={onClick}
                className="px-3 py-1.5 rounded-full text-xs font-bold flex items-center gap-1.5 transition-all"
                style={{
                  background: `rgba(${rgb},0.08)`,
                  border: `1px solid rgba(${rgb},0.25)`,
                  color: textColor,
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = `rgba(${rgb},0.18)`;
                  e.currentTarget.style.borderColor = `rgba(${rgb},0.45)`;
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = `rgba(${rgb},0.08)`;
                  e.currentTarget.style.borderColor = `rgba(${rgb},0.25)`;
                }}
              >
                <Icon className="w-3.5 h-3.5" />
                {label}
              </motion.button>
            ))}
          </div>
        </div>
      </div>

      {/* ══ MAIN GRID ══════════════════════════════════════════════════════════ */}
      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 py-8">

        {/* ── TWO-COLUMN: itinerary left · health/insights sidebar right ─── */}
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-6 items-start pb-20">

          {/* Right sidebar (stacks on top for mobile) */}
          <aside className="space-y-6 lg:order-2 lg:sticky lg:top-24 self-start">

          {/* Trip Health Widget */}
          <motion.div
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}
            className="rounded-2xl p-5"
            style={{ background: 'rgba(5,11,20,0.82)', border: '1px solid rgba(255,255,255,0.1)', backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)', boxShadow: '0 8px 32px rgba(0,0,0,0.45)' }}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl flex items-center justify-center"
                  style={{ background: 'rgba(255,107,53,0.12)', border: '1px solid rgba(255,107,53,0.25)' }}>
                  <Activity className="w-4 h-4 text-orange-400" />
                </div>
                <h3 className="font-bold text-white text-sm" style={{ fontFamily: 'var(--font-sora)' }}>Trip Health & Constraints Index</h3>
              </div>
              <span className="text-sm font-bold px-3 py-1 rounded-full"
                style={{ background: 'rgba(255,107,53,0.12)', border: '1px solid rgba(255,107,53,0.25)', color: '#FF8A65' }}>
                {trip.health_score} / 100 · GOOD
              </span>
            </div>

            {/* Health bar */}
            <div className="h-2 rounded-full overflow-hidden mb-4"
              style={{ background: 'rgba(255,255,255,0.06)' }}>
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${trip.health_score}%` }}
                transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1], delay: 0.3 }}
                className="h-full rounded-full"
                style={{ background: 'linear-gradient(90deg, #FF6B35, #FF4E6A)', boxShadow: '0 0 12px rgba(255,107,53,0.4)' }}
              />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                { label: 'Quietness', value: `${Math.round((preferences.quietness || 0.9) * 100)}% Quiet`, color: '#FF8A65', bg: 'rgba(255,107,53,0.07)' },
                { label: 'Budget Limit', value: `≤ ₹${preferences.budget_max}/act`, color: '#E2E8F0', bg: 'rgba(255,255,255,0.04)' },
                { label: 'GIS Proximity', value: 'OSM Haversine', color: '#2DD4BF', bg: 'rgba(20,184,166,0.07)' },
                { label: 'Host Direct', value: 'Rahul & Priya (0%)', color: '#34D399', bg: 'rgba(52,211,153,0.07)' },
              ].map(({ label, value, color, bg }) => (
                <div key={label} className="p-2.5 rounded-xl" style={{ background: bg, border: '1px solid rgba(255,255,255,0.07)' }}>
                  <span className="text-[10px] text-slate-500 block mb-0.5 font-medium uppercase tracking-wide">{label}</span>
                  <span className="text-xs font-bold" style={{ color }}>{value}</span>
                </div>
              ))}
            </div>
          </motion.div>

          {/* TripOS Insights */}
          {tripData.audit_actions?.filter((a: any) => a.action === 'TRIP_INSIGHT').length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.1 }}
              className="rounded-2xl p-5"
              style={{ background: 'rgba(10,14,34,0.82)', border: '1px solid rgba(99,102,241,0.35)', backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)' }}
            >
              <div className="flex items-center gap-2 mb-3">
                <Cpu className="w-4 h-4 text-indigo-400" />
                <h3 className="font-bold text-white text-sm" style={{ fontFamily: 'var(--font-sora)' }}>TripOS Optimizer Insights</h3>
              </div>
              <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                {tripData.audit_actions.filter((a: any) => a.action === 'TRIP_INSIGHT').map((insight: any) => (
                  <div key={insight.id} className="flex items-start gap-3 p-3 rounded-xl"
                    style={{ background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.15)' }}>
                    <span className="text-base shrink-0">🧠</span>
                    <p className="text-xs text-indigo-200 leading-relaxed">{insight.reason}</p>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
          </aside>

          {/* Left main column: Living Itinerary */}
          <div className="lg:order-1 min-w-0">

          {/* Living Itinerary Timeline */}
          <motion.div
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.15 }}
            className="rounded-2xl p-6"
            style={{ background: 'rgba(5,11,20,0.82)', border: '1px solid rgba(255,255,255,0.1)', backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)', boxShadow: '0 8px 32px rgba(0,0,0,0.45)' }}
          >
            {/* Day Selector */}
            <div className="flex items-center justify-between mb-6 pb-5 border-b border-white/6">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2" style={{ fontFamily: 'var(--font-sora)' }}>
                  Living Itinerary
                  <span className="text-[11px] font-bold px-2.5 py-1 rounded-full"
                    style={{ background: 'rgba(255,107,53,0.12)', border: '1px solid rgba(255,107,53,0.25)', color: '#FF8A65' }}>
                    Day {activeDay} of {Object.keys(itinerary_days).length}
                  </span>
                </h2>
                <p className="text-xs text-slate-500 mt-1">Others generate static plans. Wayzyy keeps your trip working when reality changes.</p>
              </div>
              <div className="flex gap-1 p-1 rounded-xl" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
                {Object.keys(itinerary_days).map((d) => (
                  <motion.button
                    key={d}
                    whileTap={{ scale: 0.92 }}
                    onClick={() => setActiveDay(Number(d))}
                    className="px-3.5 py-1.5 text-xs font-bold rounded-lg transition-all"
                    style={activeDay === Number(d) ? {
                      background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)',
                      color: 'white',
                      boxShadow: '0 2px 12px rgba(255,107,53,0.35)',
                    } : {
                      color: '#64748B',
                    }}
                    onMouseEnter={e => { if (activeDay !== Number(d)) (e.currentTarget as HTMLButtonElement).style.color = '#E2E8F0'; }}
                    onMouseLeave={e => { if (activeDay !== Number(d)) (e.currentTarget as HTMLButtonElement).style.color = '#64748B'; }}
                  >
                    Day {d}
                  </motion.button>
                ))}
              </div>
            </div>

            {/* Timeline */}
            <div className="space-y-4 relative">
              {/* Vertical line */}
              <div className="absolute left-[15px] top-0 bottom-4 w-px"
                style={{ background: 'linear-gradient(to bottom, rgba(255,107,53,0.4), rgba(255,107,53,0.1), transparent)' }} />

              {currentDayItems.length === 0 ? (
                <p className="text-slate-500 text-sm py-6 pl-8">No activities scheduled for Day {activeDay}.</p>
              ) : (
                <AnimatePresence>
                  {currentDayItems.map((item: any, idx: number) => {
                    const isRecovered = item.status === 'RECOVERED';
                    const isAddedByAgent = item.status === 'ADDED_BY_AGENT' || item.status === 'MODIFIED_BY_AGENT';
                    const place = item.place;
                    return (
                      <motion.div
                        key={item.item_id || idx}
                        variants={slideIn}
                        initial="hidden"
                        animate="show"
                        transition={{ delay: idx * 0.06 }}
                        className="relative pl-9 group"
                      >
                        {/* Timeline dot */}
                        <div className={`absolute left-0 top-4 w-[30px] h-[30px] rounded-full border-2 flex items-center justify-center z-10 -translate-x-0 ${
                          isRecovered ? 'border-rose-400' : isAddedByAgent ? 'border-amber-400' : 'border-orange-400'
                        }`} style={{
                          background: isRecovered ? 'rgba(244,63,94,0.2)' : isAddedByAgent ? 'rgba(245,158,11,0.2)' : 'rgba(255,107,53,0.2)',
                        }}>
                          <div className={`w-2.5 h-2.5 rounded-full ${isRecovered ? 'bg-rose-400 animate-pulse' : isAddedByAgent ? 'bg-amber-400' : 'bg-orange-400'}`} />
                        </div>

                        {/* Activity Card */}
                        <motion.div
                          variants={cardHover}
                          initial="rest"
                          whileHover="hover"
                          className="p-4 rounded-2xl transition-all"
                          style={isRecovered ? {
                            background: 'rgba(244,63,94,0.06)',
                            border: '1px solid rgba(244,63,94,0.25)',
                          } : {
                            background: 'rgba(255,255,255,0.03)',
                            border: '1px solid rgba(255,255,255,0.08)',
                          }}
                        >
                          <div className="flex flex-wrap items-start justify-between gap-2 mb-2">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-xs font-bold flex items-center gap-1" style={{ color: '#FF8A65' }}>
                                <Clock className="w-3.5 h-3.5" />{item.time_slot}
                              </span>
                              <span className="text-[11px] text-slate-500 font-medium">({item.time_period})</span>
                              {isRecovered && (
                                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1"
                                  style={{ background: 'rgba(244,63,94,0.15)', border: '1px solid rgba(244,63,94,0.3)', color: '#FDA4AF' }}>
                                  <AlertTriangle className="w-3 h-3" /> Plan B Swapped
                                </span>
                              )}
                              {isAddedByAgent && (
                                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1"
                                  style={{ background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.25)', color: '#FCD34D' }}>
                                  <Sparkles className="w-3 h-3" /> Agent Modified
                                </span>
                              )}
                            </div>
                            <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full"
                              style={{ background: 'rgba(255,255,255,0.06)', color: '#94A3B8' }}>
                              ₹{place.price}{place.price === 0 ? ' (Free)' : ''}
                            </span>
                          </div>

                          <h4 className="text-base font-bold text-white mb-1 flex items-center gap-2" style={{ fontFamily: 'var(--font-sora)' }}>
                            {place.name}
                            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                              place.indoor_flag
                                ? 'text-teal-400 bg-teal-500/10 border border-teal-500/20'
                                : 'text-amber-400 bg-amber-500/10 border border-amber-500/20'
                            }`}>
                              {place.indoor_flag ? '🏛 Indoor' : '🌊 Outdoor'}
                            </span>
                          </h4>
                          <p className="text-xs text-slate-400 mb-3 leading-relaxed">{place.description}</p>

                          <div className="flex items-center justify-between text-[11px] pt-2.5 border-t border-white/5">
                            <span className="flex items-center gap-2 flex-wrap text-slate-500">
                              <span className="flex items-center gap-1"><MapPin className="w-3 h-3 text-slate-600" />{place.area} · {place.category}</span>
                              {place.distance_km !== undefined && (
                                <span className="px-1.5 py-0.5 rounded-full flex items-center gap-1"
                                  style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)', color: '#93C5FD' }}>
                                  🚗 {place.distance_km} km
                                </span>
                              )}
                              {place.duration_hrs !== undefined && (
                                <span className="px-1.5 py-0.5 rounded-full flex items-center gap-1"
                                  style={{ background: 'rgba(168,85,247,0.08)', border: '1px solid rgba(168,85,247,0.2)', color: '#C4B5FD' }}>
                                  ⏱️ {place.duration_hrs}hr
                                </span>
                              )}
                            </span>
                            <span className="font-bold" style={{ color: '#FF8A65' }}>⭐ {place.rating} · Crowd: {place.crowd_level}</span>
                          </div>
                        </motion.div>
                      </motion.div>
                    );
                  })}
                </AnimatePresence>
              )}
            </div>

            {/* Version footer */}
            <div className="mt-6 pt-4 border-t border-white/6 flex flex-wrap items-center justify-between text-[11px] text-slate-500 gap-2">
              <span className="flex items-center gap-1.5">
                <RefreshCw className="w-3.5 h-3.5 text-orange-400" />
                Latest: {versions[0]?.change_description || 'Initial Plan'}
              </span>
              <span>Geospatial data © OpenStreetMap contributors (ODbL)</span>
            </div>
          </motion.div>
          </div>
        </div>
      </div>

      {/* ══ FLOATING AI CONCIERGE (Chatbot) ═══════════════════════════════════ */}
      
      {/* Floating Action Button (FAB) */}
      <motion.button
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => setIsChatOpen(!isChatOpen)}
        className="fixed bottom-6 right-6 w-16 h-16 rounded-full flex items-center justify-center shadow-2xl z-50 transition-colors"
        style={{ background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)', boxShadow: '0 8px 32px rgba(255,107,53,0.5)' }}
      >
        {isChatOpen ? <X className="w-7 h-7 text-white" /> : <Sparkles className="w-7 h-7 text-white" />}
      </motion.button>

      <AnimatePresence>
        {isChatOpen && (
          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.95, transformOrigin: 'bottom right' }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 40, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            className="fixed bottom-28 right-6 z-50 w-[420px] max-w-[calc(100vw-2rem)] flex flex-col overflow-hidden rounded-2xl"
            style={{
              background: 'rgba(5, 11, 20, 0.95)',
              backdropFilter: 'blur(32px)',
              WebkitBackdropFilter: 'blur(32px)',
              border: '1px solid rgba(255,255,255,0.1)',
              boxShadow: '0 24px 64px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.05)',
              height: '680px',
              maxHeight: 'calc(100vh - 9rem)',
            }}
          >
            {/* Chat header */}
            <div className="flex items-center justify-between p-5 border-b border-white/6"
              style={{ background: 'rgba(255,255,255,0.02)' }}>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl flex items-center justify-center relative"
                  style={{ background: 'linear-gradient(135deg, rgba(255,107,53,0.2), rgba(255,78,106,0.15))', border: '1px solid rgba(255,107,53,0.3)' }}>
                  <Sparkles className="w-5 h-5 text-orange-400" />
                  <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-emerald-400 rounded-full border-2 border-[#050B14]" />
                </div>
                <div>
                  <h3 className="font-bold text-white text-sm flex items-center gap-1.5" style={{ fontFamily: 'var(--font-sora)' }}>
                    Wayzyy AI Concierge
                    <CheckCircle2 className="w-3.5 h-3.5 text-orange-400" />
                  </h3>
                  <p className="text-[11px] text-slate-500">Tool-Calling & GIS Spatial Intelligence</p>
                </div>
              </div>
              <span className="text-[10px] font-bold px-2.5 py-1 rounded-full uppercase tracking-wide"
                style={{ background: 'rgba(255,107,53,0.10)', border: '1px solid rgba(255,107,53,0.22)', color: '#FF8A65' }}>
                Live Agent
              </span>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {chatMessages.map((msg, idx) => (
                <motion.div
                  key={idx}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                  className={`flex flex-col ${msg.sender === 'user' ? 'items-end' : 'items-start'}`}
                >
                  <div className={`max-w-[88%] px-4 py-3 rounded-2xl text-xs leading-relaxed font-medium ${
                    msg.sender === 'user'
                      ? 'text-white rounded-br-sm'
                      : 'text-slate-200 rounded-bl-sm'
                  }`} style={msg.sender === 'user' ? {
                    background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)',
                    boxShadow: '0 4px 16px rgba(255,107,53,0.25)',
                  } : {
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.08)',
                  }}>
                    {msg.text}
                  </div>
                  {msg.tool && (
                    <div className="mt-1.5 text-[10px] font-mono px-2.5 py-1 rounded-lg flex items-center gap-1.5"
                      style={{ background: 'rgba(20,184,166,0.08)', border: '1px solid rgba(20,184,166,0.2)', color: '#2DD4BF' }}>
                      <Zap className="w-3 h-3 text-amber-400" />
                      TOOL: <span className="font-bold">{msg.tool.name}()</span>
                    </div>
                  )}
                </motion.div>
              ))}
              {chatLoading && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                  className="flex items-center gap-2 text-[11px] text-slate-400 px-4 py-2.5 rounded-2xl w-max"
                  style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
                  <RefreshCw className="w-3.5 h-3.5 text-orange-400 animate-spin" />
                  Agent executing tool calls...
                </motion.div>
              )}
              <div ref={chatBottomRef} />
            </div>

            {/* Prompt chips */}
            <div className="flex gap-1.5 overflow-x-auto px-4 pb-2 no-scrollbar">
              {[
                { label: '📍 GIS Search within 5 km', msg: 'Search seafood spots within 5 km' },
                { label: '🌧️ Weather Check', msg: 'Will it rain tomorrow in Baga?' },
                { label: '🏠 Host tips', msg: 'Ask host for local tips' },
              ].map(({ label, msg }) => (
                <button key={label} onClick={() => handleSendMessage(msg)}
                  className="shrink-0 px-2.5 py-1.5 rounded-xl text-[11px] font-medium text-slate-400 transition-all whitespace-nowrap"
                  style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
                  onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = '#E2E8F0'; (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,107,53,0.3)'; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = '#94A3B8'; (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.08)'; }}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* Input bar */}
            <div className="p-4 pt-2 flex gap-2 items-center border-t border-white/6">
              <div className="flex-1 relative">
                <input
                  type="text"
                  value={inputMsg}
                  onChange={(e) => setInputMsg(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                  placeholder={isListening ? '🎙️ Listening...' : 'Ask agent to search places or modify itinerary...'}
                  className={`w-full px-4 py-2.5 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none transition-all ${isListening ? 'animate-pulse' : ''}`}
                  style={{
                    background: 'rgba(255,255,255,0.04)',
                    border: isListening ? '1px solid rgba(244,63,94,0.5)' : '1px solid rgba(255,255,255,0.09)',
                  }}
                  onFocus={e => { e.currentTarget.style.borderColor = 'rgba(255,107,53,0.45)'; }}
                  onBlur={e => { e.currentTarget.style.borderColor = isListening ? 'rgba(244,63,94,0.5)' : 'rgba(255,255,255,0.09)'; }}
                />
              </div>
              <motion.button whileTap={{ scale: 0.9 }} onClick={startVoiceInput} disabled={isListening}
                className="p-2.5 rounded-xl transition-all"
                style={isListening ? {
                  background: 'rgba(244,63,94,0.2)',
                  border: '1px solid rgba(244,63,94,0.4)',
                  color: '#FDA4AF',
                } : {
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.09)',
                  color: '#94A3B8',
                }}>
                {isListening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
              </motion.button>
              <motion.button whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                onClick={() => handleSendMessage()}
                className="p-2.5 rounded-xl text-white"
                style={{ background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)', boxShadow: '0 3px 12px rgba(255,107,53,0.3)' }}>
                <Send className="w-4 h-4" />
              </motion.button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══ MODAL: Weather Recovery Proposal ════════════════════════════════════ */}
      <AnimatePresence>
        {showIncidentToast && incidentResult && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(5,11,20,0.85)', backdropFilter: 'blur(12px)' }}
          >
            <motion.div
              initial={{ scale: 0.9, y: 20, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.9, y: 20, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 300, damping: 25 }}
              className="rounded-3xl p-6 max-w-lg w-full relative overflow-hidden"
              style={{ background: 'rgba(7,17,31,0.98)', border: '1px solid rgba(244,63,94,0.3)', boxShadow: '0 0 0 1px rgba(244,63,94,0.1), 0 32px 64px rgba(0,0,0,0.6)' }}
            >
              <div className="absolute top-0 right-0 w-56 h-56 rounded-full pointer-events-none -mr-16 -mt-16"
                style={{ background: 'radial-gradient(circle, rgba(244,63,94,0.12) 0%, transparent 70%)' }} />
              <div className="relative z-10">
                <div className="flex items-start justify-between mb-5">
                  <div className="flex items-center gap-3">
                    <div className="w-11 h-11 rounded-2xl flex items-center justify-center"
                      style={{ background: 'rgba(244,63,94,0.15)', border: '1px solid rgba(244,63,94,0.3)' }}>
                      <CloudRain className="w-6 h-6 text-rose-400 animate-pulse" />
                    </div>
                    <div>
                      <h3 className="text-base font-bold text-white" style={{ fontFamily: 'var(--font-sora)' }}>TripOS Detected a Disruption</h3>
                      <p className="text-xs text-rose-300">🌧️ Rain expected 2:00–5:00 PM · Beach activity affected</p>
                    </div>
                  </div>
                  <button onClick={() => setShowIncidentToast(false)} className="p-1.5 rounded-xl text-slate-500 hover:text-white transition-colors">
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="p-4 rounded-2xl mb-5"
                  style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <h4 className="text-[11px] font-bold uppercase tracking-wider mb-2" style={{ color: '#FF8A65' }}>
                    Why TripOS is recommending this recovery?
                  </h4>
                  <p className="text-xs text-slate-300 leading-relaxed">{incidentResult.why_audit}</p>

                  {incidentResult.swapped_details?.length > 0 && (
                    <div className="mt-4 pt-4 border-t border-white/6 space-y-2">
                      <span className="text-[11px] font-bold text-slate-400 block">Proposed Activity Swap:</span>
                      {incidentResult.swapped_details.map((swap: any, idx: number) => (
                        <div key={idx} className="p-3 rounded-xl" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}>
                          <div className="flex items-center gap-3">
                            <div className="flex-1">
                              <span className="line-through text-slate-500 text-[11px] block">{swap.original_place}</span>
                              <span className="font-bold text-sm flex items-center gap-1.5 mt-1" style={{ color: '#FF8A65' }}>
                                <ArrowRight className="w-3.5 h-3.5" />
                                {swap.new_place}
                                {swap.new_place_area && <span className="text-slate-400 font-normal text-xs">({swap.new_place_area})</span>}
                              </span>
                            </div>
                            <span className="text-[10px] font-bold px-2 py-1 rounded-full shrink-0"
                              style={{ background: 'rgba(255,107,53,0.12)', border: '1px solid rgba(255,107,53,0.25)', color: '#FF8A65' }}>
                              Plan B
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex gap-3">
                  <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
                    onClick={() => handleAcceptRecovery()}
                    className="flex-1 py-2.5 rounded-xl text-white text-sm font-bold flex items-center justify-center gap-2"
                    style={{ background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)', boxShadow: '0 4px 16px rgba(255,107,53,0.3)' }}>
                    <Check className="w-4 h-4" /> Accept Change
                  </motion.button>
                  <button onClick={() => setShowIncidentToast(false)}
                    className="flex-1 py-2.5 rounded-xl text-sm font-bold text-slate-300 transition-all"
                    style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                    Keep Original
                  </button>
                </div>
                {incidentResult.auto_applied && (
                  <p className="text-center text-[11px] text-emerald-400 mt-3 flex items-center justify-center gap-1">
                    <Check className="w-3 h-3" /> Auto-applied & itinerary updated
                  </p>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══ MODAL: Traffic Delay ═════════════════════════════════════════════════ */}
      <AnimatePresence>
        {showDelayModal && delayResult && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(5,11,20,0.85)', backdropFilter: 'blur(12px)' }}
          >
            <motion.div
              initial={{ scale: 0.9, y: 20, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.9, y: 20, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 300, damping: 25 }}
              className="rounded-3xl p-6 max-w-lg w-full relative overflow-hidden"
              style={{ background: 'rgba(7,17,31,0.98)', border: '1px solid rgba(99,102,241,0.3)', boxShadow: '0 32px 64px rgba(0,0,0,0.6)' }}
            >
              <div className="absolute top-0 left-0 w-48 h-48 rounded-full pointer-events-none -ml-12 -mt-12"
                style={{ background: 'radial-gradient(circle, rgba(99,102,241,0.12) 0%, transparent 70%)' }} />
              <div className="relative z-10">
                <div className="flex items-start justify-between mb-5">
                  <div className="flex items-center gap-3">
                    <div className="w-11 h-11 rounded-2xl flex items-center justify-center"
                      style={{ background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.3)' }}>
                      <Car className="w-6 h-6 text-indigo-400" />
                    </div>
                    <div>
                      <h3 className="text-base font-bold text-white" style={{ fontFamily: 'var(--font-sora)' }}>Traffic Delay Evaluation</h3>
                      <p className="text-xs text-indigo-300">d/speed matrix conflict analysis</p>
                    </div>
                  </div>
                  <button onClick={() => setShowDelayModal(false)} className="p-1.5 rounded-xl text-slate-500 hover:text-white">
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="p-4 rounded-2xl mb-5"
                  style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <p className="text-xs text-slate-300 leading-relaxed mb-3">
                    Status: <span className="font-bold" style={{ color: delayResult.status === 'CONFLICT_DETECTED' ? '#FDA4AF' : '#34D399' }}>{delayResult.status?.replace(/_/g, ' ')}</span>
                  </p>
                  {delayResult.message && <p className="text-xs text-slate-400 leading-relaxed">{delayResult.message}</p>}
                  {delayResult.proposal && (
                    <div className="mt-3 pt-3 border-t border-white/6">
                      <p className="text-[11px] font-bold text-slate-400 mb-2">AI Recovery Proposal:</p>
                      <p className="text-xs text-indigo-200">{delayResult.proposal.reason || JSON.stringify(delayResult.proposal)}</p>
                    </div>
                  )}
                  {delayResult.auto_applied && (
                    <p className="text-[11px] text-emerald-400 mt-3 flex items-center gap-1">
                      <Check className="w-3 h-3" /> Auto-applied & itinerary updated
                    </p>
                  )}
                </div>
                <button onClick={() => setShowDelayModal(false)}
                  className="w-full py-2.5 rounded-xl text-sm font-bold text-white transition-all"
                  style={{ background: 'linear-gradient(135deg, #6366F1, #8B5CF6)', boxShadow: '0 4px 16px rgba(99,102,241,0.25)' }}>
                  Got it
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══ MODAL: Right Now ════════════════════════════════════════════════════ */}
      <AnimatePresence>
        {showRightNow && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(5,11,20,0.85)', backdropFilter: 'blur(12px)' }}
          >
            <motion.div
              initial={{ scale: 0.9, y: 20, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.9, y: 20, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 300, damping: 25 }}
              className="rounded-3xl p-6 max-w-lg w-full"
              style={{ background: 'rgba(7,17,31,0.98)', border: '1px solid rgba(245,158,11,0.3)', boxShadow: '0 32px 64px rgba(0,0,0,0.6)' }}
            >
              <div className="flex items-start justify-between mb-5">
                <div className="flex items-center gap-3">
                  <div className="w-11 h-11 rounded-2xl flex items-center justify-center"
                    style={{ background: 'rgba(245,158,11,0.15)', border: '1px solid rgba(245,158,11,0.3)' }}>
                    <Zap className="w-6 h-6 text-amber-400" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-white" style={{ fontFamily: 'var(--font-sora)' }}>What to Do Right Now</h3>
                    <p className="text-xs text-amber-300">Contextual recommendations near you</p>
                  </div>
                </div>
                <button onClick={() => setShowRightNow(false)} className="p-1.5 rounded-xl text-slate-500 hover:text-white">
                  <X className="w-4 h-4" />
                </button>
              </div>
              {rightNowCandidates.length === 0 ? (
                <p className="text-xs text-slate-400 text-center py-6">No candidates found right now.</p>
              ) : (
                <div className="space-y-3 max-h-80 overflow-y-auto">
                  {rightNowCandidates.map((c: any, idx: number) => (
                    <div key={idx} className="p-4 rounded-2xl"
                      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <h4 className="font-bold text-white text-sm">{c.name || c.place?.name}</h4>
                        <span className="text-[11px] font-bold px-2 py-0.5 rounded-full shrink-0"
                          style={{ background: 'rgba(245,158,11,0.12)', color: '#FCD34D' }}>
                          ⭐ {c.rating || c.place?.rating}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400">{c.description || c.place?.description}</p>
                      {c.distance_km && <p className="text-[11px] text-teal-400 mt-1.5">📍 {c.distance_km} km away</p>}
                      <div className="flex items-center justify-between mt-3">
                        <span className="text-[11px] text-slate-500 capitalize">{c.place?.category || c.category || 'Activity'}</span>
                        <button
                          onClick={() => handleAddRecommendation(c, idx)}
                          disabled={!!addedCandidates[idx]}
                          className="flex items-center gap-1 text-[11px] font-bold px-3 py-1.5 rounded-xl transition-all disabled:cursor-default"
                          style={addedCandidates[idx]
                            ? { background: 'rgba(16,185,129,0.15)', color: '#34D399', border: '1px solid rgba(16,185,129,0.35)' }
                            : { background: 'rgba(20,184,166,0.15)', color: '#5EEAD4', border: '1px solid rgba(20,184,166,0.35)' }}
                        >
                          {addedCandidates[idx]
                            ? (<><Check className="w-3.5 h-3.5" /> Added · Day {activeDay}</>)
                            : (<><Plus className="w-3.5 h-3.5" /> Add to Day {activeDay}</>)}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══ MODAL: Host Tips ════════════════════════════════════════════════════ */}
      <AnimatePresence>
        {showHostTips && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(5,11,20,0.85)', backdropFilter: 'blur(12px)' }}
          >
            <motion.div
              initial={{ scale: 0.9, y: 20, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.9, y: 20, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 300, damping: 25 }}
              className="rounded-3xl p-6 max-w-lg w-full"
              style={{ background: 'rgba(7,17,31,0.98)', border: '1px solid rgba(20,184,166,0.3)', boxShadow: '0 32px 64px rgba(0,0,0,0.6)' }}
            >
              <div className="flex items-start justify-between mb-5">
                <div className="flex items-center gap-3">
                  <div className="w-11 h-11 rounded-2xl flex items-center justify-center"
                    style={{ background: 'rgba(20,184,166,0.15)', border: '1px solid rgba(20,184,166,0.3)' }}>
                    <Home className="w-6 h-6 text-teal-400" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-white" style={{ fontFamily: 'var(--font-sora)' }}>Direct Host Tips</h3>
                    <p className="text-xs text-teal-300">RAG-powered local intelligence from Rahul & Priya</p>
                  </div>
                </div>
                <button onClick={() => setShowHostTips(false)} className="p-1.5 rounded-xl text-slate-500 hover:text-white">
                  <X className="w-4 h-4" />
                </button>
              </div>
              {hostTips.length === 0 ? (
                <p className="text-xs text-slate-400 text-center py-6">No host tips available right now.</p>
              ) : (
                <div className="space-y-3 max-h-80 overflow-y-auto">
                  {hostTips.map((tip: any, idx: number) => (
                    <div key={idx} className="flex items-start gap-3 p-3.5 rounded-2xl"
                      style={{ background: 'rgba(20,184,166,0.06)', border: '1px solid rgba(20,184,166,0.15)' }}>
                      <span className="text-base shrink-0">💡</span>
                      <p className="text-xs text-teal-100 leading-relaxed">{tip.tip || tip}</p>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══ MODAL: Architecture Deep-Dive ══════════════════════════════════════ */}
      <AnimatePresence>
        {showArchitecture && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(5,11,20,0.88)', backdropFilter: 'blur(16px)' }}
          >
            <motion.div
              initial={{ scale: 0.9, y: 24, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.9, y: 24, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 280, damping: 24 }}
              className="rounded-3xl p-7 max-w-md w-full relative overflow-hidden"
              style={{ background: 'rgba(7,17,31,0.98)', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 32px 64px rgba(0,0,0,0.7)' }}
            >
              <div className="absolute top-0 right-0 w-48 h-48 pointer-events-none -mr-12 -mt-12"
                style={{ background: 'radial-gradient(circle, rgba(20,184,166,0.1) 0%, transparent 70%)' }} />
              <div className="relative z-10">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center"
                      style={{ background: 'rgba(20,184,166,0.12)', border: '1px solid rgba(20,184,166,0.25)' }}>
                      <Layers className="w-5 h-5 text-teal-400" />
                    </div>
                    <h3 className="font-bold text-white text-base" style={{ fontFamily: 'var(--font-sora)' }}>How TripOS Thinks</h3>
                  </div>
                  <button onClick={() => setShowArchitecture(false)} className="p-1.5 rounded-xl text-slate-500 hover:text-white">
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="space-y-2">
                  {[
                    { label: 'USER INPUT', color: 'rgba(255,107,53,0.15)', border: 'rgba(255,107,53,0.3)', text: '#FF8A65', type: 'input' },
                    { label: 'GEMINI AI AGENT', color: 'rgba(99,102,241,0.12)', border: 'rgba(99,102,241,0.3)', text: '#A5B4FC', type: 'ai' },
                    { label: 'TOOL CALLS', color: 'rgba(99,102,241,0.08)', border: 'rgba(99,102,241,0.2)', text: '#C4B5FD', type: 'ai' },
                    { label: 'GIS / RAG / TRIP TOOLS', color: 'rgba(99,102,241,0.08)', border: 'rgba(99,102,241,0.2)', text: '#C4B5FD', type: 'ai' },
                    { label: 'DETERMINISTIC TRIP ENGINE', color: 'rgba(20,184,166,0.1)', border: 'rgba(20,184,166,0.3)', text: '#2DD4BF', type: 'logic' },
                    { label: 'RANKING + CONSTRAINTS', color: 'rgba(20,184,166,0.08)', border: 'rgba(20,184,166,0.2)', text: '#5EEAD4', type: 'logic' },
                    { label: 'STATE VALIDATION', color: 'rgba(20,184,166,0.08)', border: 'rgba(20,184,166,0.2)', text: '#5EEAD4', type: 'logic' },
                    { label: 'DATABASE (SQLite)', color: 'rgba(52,211,153,0.1)', border: 'rgba(52,211,153,0.3)', text: '#34D399', type: 'output' },
                  ].map(({ label, color, border, text, type }, idx) => (
                    <div key={label}>
                      <div className="flex items-center gap-3">
                        <div className="flex-1 px-4 py-2.5 rounded-xl flex items-center justify-between"
                          style={{ background: color, border: `1px solid ${border}` }}>
                          <span className="text-xs font-bold" style={{ color }}>{label}</span>
                          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full"
                            style={{
                              background: type === 'ai' ? 'rgba(99,102,241,0.12)' : type === 'logic' ? 'rgba(20,184,166,0.1)' : 'rgba(255,255,255,0.06)',
                              color: type === 'ai' ? '#A5B4FC' : type === 'logic' ? '#2DD4BF' : '#94A3B8',
                            }}>
                            {type === 'ai' ? 'AI Reasoning' : type === 'logic' ? 'Deterministic' : ''}
                          </span>
                        </div>
                      </div>
                      {idx < 7 && (
                        <div className="flex justify-center py-0.5">
                          <div className="w-px h-3" style={{ background: 'rgba(255,255,255,0.1)' }} />
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                <div className="mt-4 flex gap-3">
                  <div className="flex items-center gap-2 text-[11px]">
                    <div className="w-3 h-3 rounded-full" style={{ background: 'rgba(99,102,241,0.5)' }} />
                    <span className="text-slate-400">AI Reasoning (Gemini)</span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px]">
                    <div className="w-3 h-3 rounded-full" style={{ background: 'rgba(20,184,166,0.5)' }} />
                    <span className="text-slate-400">Deterministic Logic</span>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
