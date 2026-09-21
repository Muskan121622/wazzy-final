'use client';

import React, { useState, useMemo, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ShieldCheck, MapPin, Sparkles, Calendar, Users, ArrowRight,
  Percent, Sliders, CheckCircle, Loader2, Search, Key,
  IndianRupee, Navigation, Check, Wind, Utensils, Zap,
  Sun, Waves, Mountain, Heart, Star, CloudSun, CloudRain
} from 'lucide-react';
import { api } from '@/lib/api';
import GoogleTranslate from '@/components/GoogleTranslate';

// ─── Animation Variants ───────────────────────────────────────────────────────
const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: 'easeOut' as const } },
};
const stagger = {
  show: { transition: { staggerChildren: 0.08 } },
};

export default function Home() {
  const router = useRouter();

  // ─── Form Fields (unchanged) ────────────────────────────────────────────────
  const [userName, setUserName] = useState('Muskan');
  const [destination, setDestination] = useState('Agonda, Canacona, Goa');
  const [selectedCoords, setSelectedCoords] = useState<{ lat: number; lon: number } | null>({ lat: 15.0441, lon: 73.9877 });

  const [startDate, setStartDate] = useState('2026-09-20');
  const [endDate, setEndDate] = useState('2026-09-24');
  const [totalBudget, setTotalBudget] = useState(15000);

  const [quietness, setQuietness] = useState(0.85);
  const [seafood, setSeafood] = useState(0.1);
  const [crowdTolerance, setCrowdTolerance] = useState(0.2);
  const [energyLevel, setEnergyLevel] = useState('medium');

  const [locationQuery, setLocationQuery] = useState('Agonda, Canacona, Goa');
  const [liveSuggestions, setLiveSuggestions] = useState<any[]>([]);
  const [isSearchingLocation, setIsSearchingLocation] = useState(false);
  const [showLocationDropdown, setShowLocationDropdown] = useState(false);
  const [isGettingGps, setIsGettingGps] = useState(false);
  const locationRef = useRef<HTMLDivElement>(null);

  const [apiKey, setApiKey] = useState('');
  const [showApiKeyInput, setShowApiKeyInput] = useState(false);

  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);

  const loadingSteps = [
    "Filtering GIS spatial radius & OpenStreetMap coordinates...",
    "Checking Open-Meteo live weather forecasts...",
    "Querying RAG Knowledge Base for authentic local host tips...",
    "Balancing budget across daily spending caps...",
    "Building dynamic Living Itinerary in SQLite...",
  ];

  // ─── Computed values (unchanged) ────────────────────────────────────────────
  const daysCount = useMemo(() => {
    try {
      const d1 = new Date(startDate);
      const d2 = new Date(endDate);
      const diffTime = Math.abs(d2.getTime() - d1.getTime());
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
      return Math.max(1, diffDays);
    } catch { return 4; }
  }, [startDate, endDate]);

  const dailyBudget = useMemo(() => Math.round(totalBudget / Math.max(1, daysCount)), [totalBudget, daysCount]);
  const maxActivityBudget = useMemo(() => Math.round(dailyBudget * 0.6), [dailyBudget]);

  // ─── Live Weather Widget (same Open-Meteo API the backend engine uses) ──────
  const [liveWeather, setLiveWeather] = useState<{ temp: number; desc: string; rainy: boolean } | null>(null);
  useEffect(() => {
    const coords = selectedCoords ?? { lat: 15.0441, lon: 73.9877 };
    let cancelled = false;
    setLiveWeather(null);
    fetch(`https://api.open-meteo.com/v1/forecast?latitude=${coords.lat}&longitude=${coords.lon}&current_weather=true`)
      .then(r => r.json())
      .then(d => {
        if (cancelled || !d?.current_weather) return;
        const code: number = d.current_weather.weathercode ?? 1;
        const rainy = [51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99].includes(code);
        const desc = code === 0 ? 'Clear sky, pleasant'
          : code <= 2 ? 'Partly cloudy, pleasant'
          : code <= 3 ? 'Overcast skies'
          : rainy ? 'Rain / monsoon showers' : 'Cloudy spells';
        setLiveWeather({ temp: Math.round(d.current_weather.temperature), desc, rainy });
      })
      .catch(() => { if (!cancelled) setLiveWeather({ temp: NaN, desc: 'Weather unavailable', rainy: false }); });
    return () => { cancelled = true; };
  }, [selectedCoords]);

  // ─── GPS Handler (unchanged) ─────────────────────────────────────────────────
  const handleUseDeviceLocation = () => {
    if (!navigator.geolocation) { alert("Geolocation is not supported by your browser."); return; }
    setIsGettingGps(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const lat = position.coords.latitude;
        const lon = position.coords.longitude;
        setSelectedCoords({ lat, lon });
        try {
          const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}`);
          const data = await res.json();
          const placeName = data.display_name || `${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E`;
          setLocationQuery(placeName); setDestination(placeName);
        } catch {
          setLocationQuery(`Current Location (${lat.toFixed(3)}, ${lon.toFixed(3)})`);
          setDestination(`Current Location (${lat.toFixed(3)}, ${lon.toFixed(3)})`);
        } finally { setIsGettingGps(false); }
      },
      (err) => { console.error("GPS Error:", err); setIsGettingGps(false); alert("Could not fetch device location. Please type manually."); },
      { timeout: 8000 }
    );
  };

  // ─── Live Location Search (unchanged) ────────────────────────────────────────
  useEffect(() => {
    if (!locationQuery || locationQuery.length < 2) { setLiveSuggestions([]); return; }
    const timer = setTimeout(async () => {
      setIsSearchingLocation(true);
      try {
        if (apiKey.trim()) {
          if (apiKey.startsWith('pk.')) {
            const res = await fetch(`https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(locationQuery)}.json?access_token=${apiKey}&limit=5`);
            const data = await res.json();
            if (data.features) setLiveSuggestions(data.features.map((f: any) => ({ display_name: f.place_name, name: f.text, lat: f.center[1], lon: f.center[0] })));
          } else {
            const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(locationQuery)}&limit=5`, { headers: { 'Accept': 'application/json', 'User-Agent': 'Wayzyy-TripOS/1.0' } });
            const data = await res.json(); setLiveSuggestions(data || []);
          }
        } else {
          const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(locationQuery)}&limit=6&addressdetails=1`, { headers: { 'Accept': 'application/json', 'User-Agent': 'Wayzyy-TripOS/1.0' } });
          const data = await res.json(); setLiveSuggestions(data || []);
        }
      } catch (err) { console.error('Live location fetch error:', err); } finally { setIsSearchingLocation(false); }
    }, 350);
    return () => clearTimeout(timer);
  }, [locationQuery, apiKey]);

  // ─── Outside click handler (unchanged) ───────────────────────────────────────
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (locationRef.current && !locationRef.current.contains(e.target as Node)) setShowLocationDropdown(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // ─── Generate Trip (unchanged) ───────────────────────────────────────────────
  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setLoadingStep(0);
    try {
      const apiPromise = api.generateTrip({
        user_name: userName,
        destination,
        days_count: daysCount,
        quietness: Number(quietness),
        seafood: Number(seafood),
        total_budget: Number(totalBudget),
        budget_max: Number(maxActivityBudget),
        crowd_tolerance: Number(crowdTolerance),
        energy_level: energyLevel,
        start_date: startDate,
        end_date: endDate,
        dest_lat: selectedCoords?.lat,
        dest_lon: selectedCoords?.lon,
      });
      for (let step = 0; step < loadingSteps.length; step++) {
        setLoadingStep(step);
        await new Promise((resolve) => setTimeout(resolve, 450));
      }
      await apiPromise;
      if (typeof window !== 'undefined') {
        localStorage.setItem('wayzyy_user_name', userName);
        localStorage.setItem('wayzyy_destination', destination);
        localStorage.setItem('wayzyy_total_budget', totalBudget.toString());
      }
      router.push(`/concierge?user_name=${encodeURIComponent(userName)}`);
    } catch (err) {
      console.error(err);
      alert('Failed to generate trip. Please make sure backend server is running on port 8000.');
    } finally { setLoading(false); }
  };

  // ─── Slider value display helper ─────────────────────────────────────────────
  const sliderPercent = (val: number) => `${Math.round(val * 100)}%`;

  return (
    <div className="min-h-screen text-slate-100 font-sans selection:bg-orange-500/30 selection:text-white relative overflow-clip">

      {/* ══ FULL PAGE BACKGROUND ══════════════════════════════════════════════ */}
      <div className="fixed inset-0 z-0 pointer-events-none">
        <img
          src="https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?w=1600&q=85"
          alt="Goa beach"
          className="w-full h-full object-cover object-center opacity-100"
        />
        {/* Soft left gradient just for the white text readability, leaves center and right bright */}
        <div className="absolute inset-0" style={{
          background: 'linear-gradient(90deg, rgba(5,11,20,0.7) 0%, rgba(5,11,20,0.1) 45%, transparent 100%)',
        }} />
        {/* Soft bottom gradient to give the cards contrast, but leaves the sky/trees bright */}
        <div className="absolute inset-0" style={{
          background: 'linear-gradient(to top, rgba(5,11,20,0.85) 0%, rgba(5,11,20,0.2) 40%, transparent 100%)',
        }} />
      </div>

      {/* ══ CINEMATIC LOADING OVERLAY ══════════════════════════════════════════ */}
      <AnimatePresence>
        {loading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-[#050B14]/95 backdrop-blur-xl z-[100] flex items-center justify-center p-6"
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 300, damping: 25 }}
              className="bg-[#07111F] border border-white/10 rounded-3xl p-8 max-w-lg w-full shadow-2xl text-center relative overflow-hidden"
            >
              <div className="absolute inset-0 rounded-3xl" style={{ background: 'radial-gradient(ellipse at top right, rgba(255,107,53,0.12) 0%, transparent 60%)' }} />
              <div className="relative z-10">
                <div className="w-16 h-16 rounded-full mx-auto flex items-center justify-center mb-6 relative"
                  style={{ background: 'rgba(255,107,53,0.1)', border: '1px solid rgba(255,107,53,0.3)' }}>
                  <Loader2 className="w-7 h-7 text-orange-400 animate-spin" />
                  <div className="absolute inset-0 rounded-full animate-ping" style={{ background: 'rgba(255,107,53,0.08)' }} />
                </div>
                <h3 className="text-xl font-bold text-white mb-1" style={{ fontFamily: 'var(--font-sora)' }}>Engine Computing TripOS Matrix</h3>
                <p className="text-xs text-slate-400 mb-7">Running 5-Factor Scoring, Haversine GIS distances & RAG lookup</p>
                <div className="space-y-2.5 text-left mb-7">
                  {loadingSteps.map((stepText, idx) => (
                    <motion.div
                      key={idx}
                      initial={{ opacity: 0.4 }}
                      animate={{ opacity: idx <= loadingStep ? 1 : 0.4 }}
                      className={`flex items-center gap-3 p-3 rounded-xl border text-xs font-medium transition-all ${
                        idx < loadingStep
                          ? 'bg-emerald-500/8 border-emerald-500/25 text-emerald-400'
                          : idx === loadingStep
                          ? 'bg-orange-500/10 border-orange-500/35 text-white'
                          : 'bg-white/3 border-white/6 text-slate-500'
                      }`}
                    >
                      {idx < loadingStep ? (
                        <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                      ) : idx === loadingStep ? (
                        <Loader2 className="w-4 h-4 text-orange-400 animate-spin shrink-0" />
                      ) : (
                        <div className="w-4 h-4 rounded-full border border-slate-600 shrink-0" />
                      )}
                      <span>{stepText}</span>
                    </motion.div>
                  ))}
                </div>
                <span className="text-[11px] font-bold text-orange-400 uppercase tracking-widest">Wayzyy Autonomous Engine Active</span>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══ MARQUEE BAR ════════════════════════════════════════════════════════ */}
      <div className="border-b border-white/6 overflow-hidden py-2.5" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <div className="max-w-7xl mx-auto flex items-center justify-between px-6">
          <div className="flex items-center gap-5 overflow-x-auto whitespace-nowrap no-scrollbar text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500">
            <span className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse inline-block" />0% Booking Commission</span>
            <span className="text-white/15">✦</span>
            <span>Aadhaar Verified Identity</span>
            <span className="text-white/15">✦</span>
            <span>100% Direct Host Connection</span>
            <span className="text-white/15">✦</span>
            <span className="text-white/60">Wayzyy TripOS Active</span>
            <span className="text-white/15">✦</span>
            <span>Honest Pricing</span>
          </div>
          <span className="hidden md:flex items-center gap-2 text-[11px] text-slate-500 uppercase tracking-wider shrink-0">
            <CloudSun className="w-3.5 h-3.5 text-orange-400" /> Goa Homestays & Villas
          </span>
        </div>
      </div>

      {/* ══ HEADER ═════════════════════════════════════════════════════════════ */}
      <header className="sticky top-0 z-50 border-b border-white/8"
        style={{ background: 'rgba(5,11,20,0.85)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)' }}>
        <div className="max-w-7xl mx-auto px-6 h-[68px] flex items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center font-black text-[#050B14] text-lg shadow-lg"
              style={{ background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)', boxShadow: '0 4px 16px rgba(255,107,53,0.4)' }}>
              W
            </div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-xl text-white tracking-tight" style={{ fontFamily: 'var(--font-sora)' }}>Wayzyy</span>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider"
                style={{ background: 'rgba(255,107,53,0.12)', border: '1px solid rgba(255,107,53,0.3)', color: '#FF6B35' }}>
                TripOS
              </span>
            </div>
          </div>

          {/* Global Search */}
          <div className="hidden lg:flex items-center gap-3 flex-1 max-w-md mx-8">
            <div className="flex-1 flex items-center gap-2.5 px-4 py-2.5 rounded-full text-sm text-slate-500"
              style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <Search className="w-4 h-4 shrink-0" />
              <span className="text-xs">What can I help you discover?</span>
            </div>
          </div>

          {/* Right actions */}
          <div className="flex items-center gap-2.5">
            <GoogleTranslate />
            <button
              onClick={() => setShowApiKeyInput(!showApiKeyInput)}
              className="hidden sm:flex px-3 py-2 text-xs font-semibold rounded-full items-center gap-1.5 text-slate-400 transition-all hover:text-white"
              style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
            >
              <Key className="w-3.5 h-3.5 text-orange-400" />
              {apiKey ? 'API Key Active' : 'Custom API Key'}
            </button>
            <motion.button
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => router.push('/concierge')}
              className="px-4 py-2 text-xs font-bold rounded-full text-white flex items-center gap-2 transition-all"
              style={{ background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)', boxShadow: '0 4px 16px rgba(255,107,53,0.35)' }}
            >
              <Sparkles className="w-3.5 h-3.5" />
              View Living Dashboard
            </motion.button>
          </div>
        </div>
      </header>

      {/* API Key drawer */}
      <AnimatePresence>
        {showApiKeyInput && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-b border-orange-500/20 overflow-hidden"
            style={{ background: 'rgba(255,107,53,0.04)' }}
          >
            <div className="max-w-7xl mx-auto px-6 py-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs text-slate-300">
                <Key className="w-3.5 h-3.5 text-orange-400" />
                <span className="font-semibold">Google Places / Mapbox API Key Integration:</span>
                <span className="text-slate-500">Paste your API key below for custom places geocoding.</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Paste Google Places Key / Mapbox Token"
                  className="px-3 py-1.5 rounded-lg text-white text-xs w-64 focus:outline-none"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.15)' }}
                />
                <button onClick={() => setShowApiKeyInput(false)}
                  className="px-3 py-1.5 rounded-lg text-white font-bold text-xs"
                  style={{ background: 'linear-gradient(135deg, #FF6B35, #FF4E6A)' }}>
                  Save
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══ HERO (Content Only) ════════════════════════════════════════════════ */}
      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 pt-16 pb-12">
        <motion.div variants={stagger} initial="hidden" animate="show" className="max-w-2xl">
          <motion.div variants={fadeUp} className="flex items-center gap-2.5 mb-6">
            <span className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest px-3 py-1.5 rounded-full"
              style={{ background: 'rgba(255,107,53,0.18)', border: '1px solid rgba(255,107,53,0.4)', color: '#FF8A65', backdropFilter: 'blur(8px)' }}>
              <Sparkles className="w-3.5 h-3.5" /> AI-Powered
            </span>
          </motion.div>
          
          <motion.h1 variants={fadeUp}
            className="text-5xl md:text-[4rem] lg:text-[4.5rem] font-bold text-white leading-[1.05] mb-6 tracking-tight"
            style={{ fontFamily: 'var(--font-sora)', textShadow: '0 4px 32px rgba(0,0,0,0.6)' }}>
            Generate Your<br />
            <span style={{ background: 'linear-gradient(135deg, #FF6B35, #FF4E6A, #FF8A65)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text', textShadow: 'none' }}>
              Living Itinerary
            </span>
          </motion.h1>
          
          <motion.p variants={fadeUp} className="text-slate-200 text-base md:text-lg max-w-lg leading-relaxed"
            style={{ textShadow: '0 2px 12px rgba(0,0,0,0.8)' }}>
            Tell us what makes a great trip for you.{' '}
            <span className="text-white font-bold">Wayzyy will build an itinerary</span>{' '}
            that adapts as your trip changes.
          </motion.p>
        </motion.div>

        {/* Decorative Goa script — right side */}
        <div className="absolute top-1/2 -translate-y-1/2 right-12 text-right hidden lg:block pointer-events-none">
          <span className="text-[5rem] font-bold opacity-30 text-white italic" style={{ fontFamily: 'Georgia, serif', textShadow: '0 4px 24px rgba(0,0,0,0.4)' }}>
            Goa
          </span>
          <br />
          <span className="text-3xl font-light opacity-25 text-white italic" style={{ fontFamily: 'Georgia, serif' }}>
            Awaits
          </span>
        </div>
      </div>

      {/* ══ MAIN LAYOUT: Form + Right Sidebar ══════════════════════════════════ */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 pb-20 relative z-10">
        <div className="grid lg:grid-cols-3 gap-7">

          {/* ── LEFT/MAIN: Trip DNA Form ──────────────────────────────────────── */}
          <motion.div
            initial={{ opacity: 0, y: 32 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="lg:col-span-2"
          >
            {/* Trip DNA Card */}
            <div className="rounded-3xl overflow-hidden relative"
              style={{ background: 'rgba(5,11,20,0.65)', border: '1px solid rgba(255,255,255,0.1)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)', boxShadow: '0 0 0 1px rgba(255,255,255,0.03), 0 32px 64px rgba(0,0,0,0.6)' }}>

              {/* Ambient glow */}
              <div className="absolute top-0 right-0 w-80 h-80 rounded-full pointer-events-none -mr-24 -mt-24"
                style={{ background: 'radial-gradient(circle, rgba(255,107,53,0.10) 0%, transparent 70%)' }} />
              <div className="absolute bottom-0 left-0 w-64 h-64 rounded-full pointer-events-none -ml-16 -mb-16"
                style={{ background: 'radial-gradient(circle, rgba(20,184,166,0.06) 0%, transparent 70%)' }} />

              <div className="relative z-10 p-6 md:p-8">
                {/* Card Header */}
                <div className="flex items-center justify-between mb-7">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl flex items-center justify-center"
                      style={{ background: 'rgba(255,107,53,0.12)', border: '1px solid rgba(255,107,53,0.25)' }}>
                      <Sliders className="w-4.5 h-4.5 text-orange-400" />
                    </div>
                    <div>
                      <h2 className="text-lg font-bold text-white" style={{ fontFamily: 'var(--font-sora)' }}>Your Trip DNA</h2>
                      <p className="text-xs text-slate-500">Set your preferences and let our AI find the perfect experiences for you.</p>
                    </div>
                  </div>
                  <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold"
                    style={{ background: 'rgba(20,184,166,0.08)', border: '1px solid rgba(20,184,166,0.2)', color: '#2DD4BF' }}>
                    <CheckCircle className="w-3.5 h-3.5" /> Post-Booking Engine
                  </div>
                </div>

                {/* Destination tags (moved from hero) */}
                <div className="flex items-center gap-2 flex-wrap mb-7 pb-6 border-b border-white/5">
                  {['Beaches', 'Food', 'Culture', 'Serenity', 'You'].map((tag, i) => (
                    <span key={tag} className="text-[11px] font-semibold px-3 py-1.5 rounded-full"
                      style={{
                        background: i === 4 ? 'rgba(255,107,53,0.15)' : 'rgba(255,255,255,0.03)',
                        border: i === 4 ? '1px solid rgba(255,107,53,0.3)' : '1px solid rgba(255,255,255,0.08)',
                        color: i === 4 ? '#FF8A65' : 'rgba(255,255,255,0.5)',
                      }}>
                      {tag}
                    </span>
                  ))}
                </div>

                <form onSubmit={handleGenerate}>
                  {/* ── Row 1: Traveler + Destination + Dates ── */}
                  <div className="grid sm:grid-cols-2 lg:grid-cols-[1fr_1.5fr_1fr_1fr] gap-4 mb-6">

                    {/* Traveler Name */}
                    <div className="lg:col-span-1">
                      <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Traveler</label>
                      <div className="relative">
                        <Users className="w-4 h-4 text-slate-500 absolute left-3.5 top-3.5 pointer-events-none" />
                        <input
                          type="text"
                          value={userName}
                          onChange={(e) => setUserName(e.target.value)}
                          className="w-full pl-10 pr-3 py-3 rounded-xl text-white text-sm focus:outline-none transition-all"
                          style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.09)' }}
                          onFocus={e => { e.currentTarget.style.borderColor = 'rgba(255,107,53,0.5)'; e.currentTarget.style.background = 'rgba(255,107,53,0.05)'; }}
                          onBlur={e => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.09)'; e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
                          placeholder="Your Name"
                          required
                        />
                      </div>
                    </div>

                    {/* Destination with live autocomplete */}
                    <div className="lg:col-span-1 relative" ref={locationRef}>
                      <div className="flex justify-between items-center mb-2">
                        <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider">Destination</label>
                        <button type="button" onClick={handleUseDeviceLocation} disabled={isGettingGps}
                          className="text-[10px] font-bold text-orange-400 hover:text-orange-300 flex items-center gap-1 transition-colors">
                          {isGettingGps ? <Loader2 className="w-3 h-3 animate-spin" /> : <Navigation className="w-3 h-3" />}
                          GPS
                        </button>
                      </div>
                      <div className="relative">
                        <MapPin className="w-4 h-4 text-orange-400 absolute left-3.5 top-3.5 pointer-events-none" />
                        <input
                          type="text"
                          value={locationQuery}
                          onChange={(e) => { setLocationQuery(e.target.value); setDestination(e.target.value); setShowLocationDropdown(true); }}
                          onFocus={() => setShowLocationDropdown(true)}
                          className="w-full pl-10 pr-8 py-3 rounded-xl text-white text-sm focus:outline-none transition-all"
                          style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.09)' }}
                          placeholder="City or location..."
                          required
                        />
                        {isSearchingLocation && <Loader2 className="w-3.5 h-3.5 text-orange-400 animate-spin absolute right-3 top-3.5" />}
                      </div>
                      {/* Live suggestions dropdown */}
                      <AnimatePresence>
                        {showLocationDropdown && (
                          <motion.div
                            initial={{ opacity: 0, y: -8 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -8 }}
                            transition={{ duration: 0.15 }}
                            className="absolute left-0 right-0 top-full mt-1.5 rounded-2xl shadow-2xl z-50 max-h-60 overflow-y-auto"
                            style={{ background: 'rgba(7,17,31,0.98)', border: '1px solid rgba(255,255,255,0.12)', backdropFilter: 'blur(20px)' }}
                          >
                            {isSearchingLocation ? (
                              <div className="p-4 flex items-center gap-2 text-xs text-slate-400">
                                <Loader2 className="w-3.5 h-3.5 text-orange-400 animate-spin" />Fetching live coordinates...
                              </div>
                            ) : liveSuggestions.length === 0 ? (
                              <div className="p-3 text-xs text-slate-500">Type a location to see suggestions</div>
                            ) : liveSuggestions.map((item: any, idx: number) => {
                              const name = item.display_name || item.name || 'Location';
                              const parts = name.split(',');
                              const title = parts[0];
                              const subtitle = parts.slice(1, 3).join(',');
                              return (
                                <button key={idx} type="button"
                                  onClick={() => { setLocationQuery(title); setDestination(name); if (item.lat && item.lon) setSelectedCoords({ lat: parseFloat(item.lat), lon: parseFloat(item.lon) }); setShowLocationDropdown(false); }}
                                  className="w-full p-3 text-left flex items-start gap-3 group transition-colors border-b border-white/4 last:border-0"
                                  style={{ background: 'transparent' }}
                                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,107,53,0.06)')}
                                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                                >
                                  <MapPin className="w-4 h-4 text-orange-400 shrink-0 mt-0.5" />
                                  <div>
                                    <span className="text-xs font-semibold text-white block">{title}</span>
                                    <span className="text-[11px] text-slate-500 block line-clamp-1">{subtitle || name}</span>
                                    {item.lat && (
                                      <span className="text-[10px] text-teal-400 font-mono mt-0.5 block">
                                        GIS: {Number(item.lat).toFixed(4)}°N, {Number(item.lon).toFixed(4)}°E
                                      </span>
                                    )}
                                  </div>
                                </button>
                              );
                            })}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>

                    {/* Check-in */}
                    <div>
                      <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Check-in</label>
                      <div className="relative">
                        <Calendar className="w-4 h-4 text-orange-400 absolute left-3.5 top-3.5 pointer-events-none" />
                        <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
                          className="w-full pl-10 pr-3 py-3 rounded-xl text-white text-sm focus:outline-none transition-all scheme-dark"
                          style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.09)' }}
                          required />
                      </div>
                    </div>

                    {/* Check-out */}
                    <div>
                      <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Check-out</label>
                      <div className="relative">
                        <Calendar className="w-4 h-4 text-orange-400 absolute left-3.5 top-3.5 pointer-events-none" />
                        <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
                          className="w-full pl-10 pr-3 py-3 rounded-xl text-white text-sm focus:outline-none transition-all scheme-dark"
                          style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.09)' }}
                          required />
                      </div>
                    </div>
                  </div>

                  {/* ── Budget Summary Stats ── */}
                  <div className="grid grid-cols-3 gap-3 mb-7 p-4 rounded-2xl"
                    style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.07)' }}>
                    {[
                      { icon: Calendar, label: 'Trip Duration', value: `${daysCount} Days`, color: '#FF8A65', bg: 'rgba(255,107,53,0.10)', border: 'rgba(255,107,53,0.25)' },
                      { icon: IndianRupee, label: 'Daily Budget', value: `₹${dailyBudget.toLocaleString()}/day`, color: '#34D399', bg: 'rgba(52,211,153,0.08)', border: 'rgba(52,211,153,0.2)' },
                      { icon: Sliders, label: 'Max/Activity', value: `≤ ₹${maxActivityBudget.toLocaleString()}`, color: '#FBBF24', bg: 'rgba(251,191,36,0.08)', border: 'rgba(251,191,36,0.2)' },
                    ].map(({ icon: Icon, label, value, color, bg, border }) => (
                      <div key={label} className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
                          style={{ background: bg, border: `1px solid ${border}` }}>
                          <Icon className="w-4 h-4" style={{ color }} />
                        </div>
                        <div className="min-w-0">
                          <span className="text-[10px] text-slate-500 block uppercase tracking-wide font-semibold">{label}</span>
                          <span className="text-sm font-bold truncate block" style={{ color }}>{value}</span>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* ── Preferences Section ── */}
                  <div className="border-t border-white/6 pt-7 mb-7">
                    <div className="flex items-center gap-2 mb-6">
                      <div className="w-1 h-5 rounded-full" style={{ background: 'linear-gradient(to bottom, #FF6B35, #FF4E6A)' }} />
                      <h3 className="text-sm font-bold text-white uppercase tracking-wider" style={{ fontFamily: 'var(--font-sora)' }}>
                        Preferences
                      </h3>
                    </div>

                    <div className="grid md:grid-cols-2 gap-7">
                      {/* Total Budget slider */}
                      <div>
                        <div className="flex justify-between items-center mb-3">
                          <span className="text-xs font-semibold text-slate-300">Total Trip Budget</span>
                          <div className="relative flex items-center">
                            <span className="text-xs font-bold absolute left-2.5" style={{ color: '#34D399' }}>₹</span>
                            <input type="number" min="500" max="200000" step="500" value={totalBudget}
                              onChange={(e) => setTotalBudget(Math.max(0, Number(e.target.value)))}
                              className="w-28 pl-6 pr-2 py-1 rounded-lg text-xs font-bold focus:outline-none"
                              style={{ background: 'rgba(52,211,153,0.06)', border: '1px solid rgba(52,211,153,0.3)', color: '#34D399' }} />
                          </div>
                        </div>
                        <input type="range" min="1000" max="50000" step="500" value={totalBudget}
                          onChange={(e) => setTotalBudget(Number(e.target.value))} className="w-full" />
                        <p className="text-[11px] text-slate-500 mt-2">~₹{dailyBudget.toLocaleString()} / day · stays within your total limit</p>
                      </div>

                      {/* Quietness */}
                      <div>
                        <div className="flex justify-between items-center mb-3">
                          <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                            <Wind className="w-3.5 h-3.5 text-teal-400" /> Quietness Preference
                          </span>
                          <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full"
                            style={{ background: 'rgba(255,107,53,0.12)', border: '1px solid rgba(255,107,53,0.25)', color: '#FF8A65' }}>
                            {sliderPercent(quietness)} Quiet
                          </span>
                        </div>
                        <input type="range" min="0.1" max="1.0" step="0.05" value={quietness}
                          onChange={(e) => setQuietness(Number(e.target.value))} className="w-full" />
                        <p className="text-[11px] text-slate-500 mt-2">Calm coves, heritage villas & low-crowd cafes</p>
                      </div>

                      {/* Seafood */}
                      <div>
                        <div className="flex justify-between items-center mb-3">
                          <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                            <Utensils className="w-3.5 h-3.5 text-amber-400" /> Seafood & Coastal Food
                          </span>
                          <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full"
                            style={{ background: 'rgba(251,191,36,0.10)', border: '1px solid rgba(251,191,36,0.25)', color: '#FBBF24' }}>
                            {sliderPercent(seafood)} Priority
                          </span>
                        </div>
                        <input type="range" min="0.0" max="1.0" step="0.1" value={seafood}
                          onChange={(e) => setSeafood(Number(e.target.value))} className="w-full" />
                      </div>

                      {/* Energy Level */}
                      <div>
                        <span className="text-xs font-semibold text-slate-300 block mb-3 flex items-center gap-1.5">
                          <Zap className="w-3.5 h-3.5 text-yellow-400" /> Pacing & Energy Level
                        </span>
                        <div className="flex gap-2">
                          {[
                            { id: 'relaxed', label: 'Relaxed', emoji: '🌊' },
                            { id: 'medium', label: 'Medium', emoji: '☀️' },
                            { id: 'high', label: 'High', emoji: '⚡' },
                          ].map(({ id, label, emoji }) => (
                            <motion.button
                              key={id}
                              type="button"
                              whileTap={{ scale: 0.95 }}
                              onClick={() => setEnergyLevel(id)}
                              className="flex-1 py-2.5 text-xs font-bold rounded-xl flex items-center justify-center gap-1.5 transition-all"
                              style={energyLevel === id ? {
                                background: 'linear-gradient(135deg, rgba(255,107,53,0.25), rgba(255,78,106,0.2))',
                                border: '1px solid rgba(255,107,53,0.5)',
                                color: '#FF8A65',
                                boxShadow: '0 0 16px rgba(255,107,53,0.2)',
                              } : {
                                background: 'rgba(255,255,255,0.04)',
                                border: '1px solid rgba(255,255,255,0.08)',
                                color: '#94A3B8',
                              }}
                            >
                              <span>{emoji}</span> {label}
                            </motion.button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* ── CTA Button ── */}
                  <motion.button
                    type="submit"
                    disabled={loading}
                    whileHover={!loading ? { scale: 1.02, y: -2 } : {}}
                    whileTap={!loading ? { scale: 0.98 } : {}}
                    className="w-full py-4 rounded-2xl text-white font-bold text-sm flex items-center justify-center gap-3 transition-all disabled:opacity-50 disabled:cursor-not-allowed relative overflow-hidden"
                    style={{
                      background: 'linear-gradient(135deg, #FF6B35 0%, #FF4E6A 50%, #FF8A65 100%)',
                      boxShadow: '0 0 40px rgba(255,107,53,0.35), 0 8px 32px rgba(255,78,106,0.25)',
                    }}
                  >
                    <div className="absolute inset-0 opacity-0 hover:opacity-100 transition-opacity"
                      style={{ background: 'linear-gradient(135deg, rgba(255,255,255,0.08) 0%, transparent 100%)' }} />
                    {loading ? (
                      <><Loader2 className="w-5 h-5 animate-spin" />Running 5-Factor Scoring & Budget Optimization Engine...</>
                    ) : (
                      <><Sparkles className="w-5 h-5" />Generate My Living Itinerary<ArrowRight className="w-4 h-4" /></>
                    )}
                  </motion.button>

                  {/* Trust badges */}
                  <div className="flex items-center justify-center gap-6 mt-5">
                    {[
                      { icon: ShieldCheck, label: '0% Commission', color: 'text-teal-400' },
                      { icon: MapPin, label: 'OSM GIS Engine', color: 'text-orange-400' },
                      { icon: Percent, label: 'Direct Host', color: 'text-emerald-400' },
                    ].map(({ icon: Icon, label, color }) => (
                      <div key={label} className={`flex items-center gap-1.5 text-[11px] font-medium text-slate-500 ${color}`}>
                        <Icon className={`w-3.5 h-3.5 ${color}`} />{label}
                      </div>
                    ))}
                  </div>
                </form>
              </div>
            </div>
          </motion.div>

          {/* ── RIGHT SIDEBAR ─────────────────────────────────────────────────── */}
          <motion.div
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.6, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
            className="lg:col-span-1 space-y-5"
          >
            {/* Weather + Quote Widget */}
            <div className="rounded-2xl p-5 relative overflow-hidden"
              style={{ background: 'rgba(5,11,20,0.65)', border: '1px solid rgba(255,255,255,0.1)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)' }}>              <div className="absolute top-0 right-0 w-32 h-32 rounded-full pointer-events-none -mr-8 -mt-8"
                style={{ background: 'radial-gradient(circle, rgba(251,191,36,0.08) 0%, transparent 70%)' }} />
              <div className="flex items-start justify-between mb-4">
                <div>
                  <p className="text-2xl font-bold text-white">
                    {liveWeather ? (Number.isNaN(liveWeather.temp) ? '—' : `${liveWeather.temp}°C`) : '··'}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5 flex items-center gap-1">
                    <MapPin className="w-3 h-3 text-orange-400" /> {(destination.split(',')[0].trim() || 'Goa')}, India
                  </p>
                </div>
                <div className="text-right">
                  {liveWeather?.rainy
                    ? <CloudRain className="w-8 h-8 text-sky-400 ml-auto mb-1" />
                    : <CloudSun className="w-8 h-8 text-yellow-400 ml-auto mb-1" />}
                  <p className="text-[11px] text-slate-400 leading-tight max-w-[110px]">
                    {liveWeather ? liveWeather.desc : 'Fetching live weather...'}
                  </p>
                </div>
              </div>
              <p className="text-xs text-slate-400 italic border-t border-white/6 pt-3">
                "The best journeys are the ones that adapt."
                <span className="block text-orange-400 font-medium not-italic mt-1">— Wayzyy TripOS</span>
              </p>
            </div>

            {/* Popular near Goa */}
            <div className="rounded-2xl overflow-hidden"
              style={{ background: 'rgba(5,11,20,0.65)', border: '1px solid rgba(255,255,255,0.1)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)' }}>              <div className="flex items-center justify-between px-5 pt-5 pb-3">
                <h3 className="text-sm font-bold text-white flex items-center gap-2" style={{ fontFamily: 'var(--font-sora)' }}>
                  <span className="text-orange-400">🔥</span> Popular in Goa
                </h3>
                <button className="text-[11px] text-orange-400 font-medium hover:text-orange-300 transition-colors">See all →</button>
              </div>
              <div className="divide-y divide-white/5">
                {[
                  { name: 'Palolem Beach', tag: 'Serene', rating: 4.9, img: 'https://images.unsplash.com/photo-1506929562872-bb421503ef21?w=120&q=75' },
                  { name: 'Cola Beach', tag: 'Hidden Gem', rating: 4.7, img: 'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=120&q=75' },
                  { name: 'Fontainhas', tag: 'Heritage', rating: 4.6, img: 'https://images.unsplash.com/photo-1564501049412-61c2a3083791?w=120&q=75' },
                ].map((place) => (
                  <motion.div
                    key={place.name}
                    whileHover={{ x: 2, backgroundColor: 'rgba(255,255,255,0.03)' }}
                    className="flex items-center gap-3.5 px-5 py-3.5 transition-colors group"
                  >
                    <div className="w-12 h-12 rounded-xl overflow-hidden shrink-0 ring-1 ring-white/8"
                      style={{ background: 'linear-gradient(135deg, rgba(255,107,53,0.3), rgba(20,184,166,0.25))' }}>
                      <img src={place.img} alt={place.name} loading="lazy" className="w-full h-full object-cover"
                        onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-white truncate">{place.name}</p>
                      <p className="text-[11px] text-slate-500">{place.tag} · ⭐ {place.rating}</p>
                    </div>
                    <Heart className="w-4 h-4 text-slate-600 group-hover:text-orange-400 transition-colors shrink-0" />
                  </motion.div>
                ))}
              </div>
            </div>

            {/* Why Wayzyy? */}
            <div className="rounded-2xl p-5 relative overflow-hidden"
              style={{ background: 'rgba(5,11,20,0.65)', border: '1px solid rgba(255,255,255,0.1)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)' }}>              <div className="absolute bottom-0 right-0 w-32 h-32 pointer-events-none -mr-8 -mb-8"
                style={{ background: 'radial-gradient(circle, rgba(20,184,166,0.08) 0%, transparent 70%)' }} />
              <h3 className="text-sm font-bold text-white mb-4" style={{ fontFamily: 'var(--font-sora)' }}>Why Wayzyy?</h3>
              <div className="space-y-3">
                {[
                  { icon: '🌤️', title: 'Real-time weather adaptation', desc: 'Plans adjust to live forecasts' },
                  { icon: '🗺️', title: 'Smart route optimization', desc: 'GIS Haversine distance engine' },
                  { icon: '⚡', title: 'Living itinerary', desc: 'Adapts when reality changes' },
                  { icon: '🎯', title: 'Personalized for your vibe', desc: 'AI matches your preferences' },
                  { icon: '🏠', title: 'Local host intelligence', desc: 'RAG-powered insider tips' },
                ].map(({ icon, title, desc }) => (
                  <div key={title} className="flex items-start gap-3">
                    <span className="text-base shrink-0 mt-0.5">{icon}</span>
                    <div>
                      <p className="text-xs font-semibold text-slate-200">{title}</p>
                      <p className="text-[11px] text-slate-500">{desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Bottom tagline */}
            <div className="rounded-2xl p-5 text-center"
              style={{ background: 'linear-gradient(135deg, rgba(255,107,53,0.08), rgba(255,78,106,0.05))', border: '1px solid rgba(255,107,53,0.2)' }}>
              <p className="text-sm font-bold text-white mb-1" style={{ fontFamily: 'var(--font-sora)' }}>
                "Not just a trip.<br />A better you."
              </p>
              <p className="text-[11px] text-orange-400 font-medium">— Wayzyy</p>
            </div>
          </motion.div>
        </div>
      </main>
    </div>
  );
}
