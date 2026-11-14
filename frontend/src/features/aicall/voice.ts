// Voix de l'appel : reconnaissance vocale et synthèse du navigateur (Web Speech, gratuites, Chrome / Edge).
// Interface volontairement étroite pour brancher plus tard un fournisseur payant (Azure Speech, ElevenLabs…).

type Rec = {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null; onspeechstart: (() => void) | null;
  start: () => void; stop: () => void; abort: () => void;
};

export const canListen = () => typeof window !== "undefined" && !!((window as unknown as Record<string, unknown>).SpeechRecognition || (window as unknown as Record<string, unknown>).webkitSpeechRecognition);
export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window;

/** Micro continu : `onFinal` reçoit chaque phrase terminée, `onInterim` le texte en cours, `onVoice` dès que l'humain parle. */
export function createListener(h: { onFinal: (t: string) => void; onInterim: (t: string) => void; onVoice: () => void; onState: (on: boolean, err?: string) => void }) {
  const W = window as unknown as { SpeechRecognition?: new () => Rec; webkitSpeechRecognition?: new () => Rec };
  const Ctor = W.SpeechRecognition ?? W.webkitSpeechRecognition;
  if (!Ctor) return null;
  let wanted = false;
  let rec: Rec | null = null;
  const boot = () => {
    rec = new Ctor();
    rec.lang = "fr-FR";
    rec.continuous = true;
    rec.interimResults = true;
    rec.onspeechstart = () => h.onVoice();
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        const t = r[0]?.transcript ?? "";
        if (r.isFinal) {
          if (t.trim()) h.onFinal(t.trim());
        } else interim += t;
      }
      h.onInterim(interim);
      if (interim) h.onVoice();
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        wanted = false;
        h.onState(false, "Micro refusé par le navigateur.");
      }
    };
    rec.onend = () => {
      if (wanted) setTimeout(() => { try { boot(); rec?.start(); } catch { /* déjà démarré */ } }, 250);
      else h.onState(false);
    };
  };
  return {
    start() {
      wanted = true;
      boot();
      try { rec?.start(); h.onState(true); } catch { /* déjà démarré */ }
    },
    stop() {
      wanted = false;
      try { rec?.stop(); } catch { /* */ }
      h.onState(false);
    },
  };
}

let frVoices: SpeechSynthesisVoice[] = [];
function voices() {
  if (!canSpeak()) return [];
  if (!frVoices.length) frVoices = window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("fr"));
  return frVoices;
}
if (canSpeak()) window.speechSynthesis.onvoiceschanged = () => { frVoices = []; voices(); };

/** Une voix différente par assistant (selon les voix françaises installées), hauteur légèrement variée. */
export function speak(text: string, who: string, cb: { onStart: () => void; onWord: () => void; onEnd: () => void }) {
  if (!canSpeak()) return cb.onEnd();
  const u = new SpeechSynthesisUtterance(text.replace(/[«»"*_#]/g, ""));
  const list = voices();
  const seed = [...who].reduce((a, c) => a + c.charCodeAt(0), 0);
  if (list.length) u.voice = list[seed % list.length];
  u.lang = "fr-FR";
  u.rate = 1.04;
  u.pitch = who === "maestro" ? 0.85 : 0.95 + (seed % 5) * 0.06;
  u.onstart = cb.onStart;
  u.onboundary = cb.onWord;
  u.onend = cb.onEnd;
  u.onerror = cb.onEnd;
  window.speechSynthesis.speak(u);
}

export function hush() {
  if (canSpeak()) window.speechSynthesis.cancel();
}
