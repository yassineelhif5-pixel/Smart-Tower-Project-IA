// Avatar 3D d'un assistant (Three.js chargé à la demande depuis le CDN, comme Tesseract.js), avec repli 2D animé.
// La bouche suit la voix : `mouth.current` passe à 1 à chaque mot prononcé et retombe progressivement.
import { useEffect, useRef, useState, type MutableRefObject } from "react";

export type AvatarState = "idle" | "listening" | "thinking" | "speaking";

const THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Three = any;
let threeLib: Promise<Three> | null = null;
function loadThree(): Promise<Three> {
  threeLib ??= (import(/* @vite-ignore */ THREE_URL) as Promise<Three>).catch((e) => {
    threeLib = null;
    throw e;
  });
  return threeLib;
}

function hasWebGL() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

type Props = { code: string; color: string; name: string; state: AvatarState; mouth: MutableRefObject<number>; size?: "stage" | "tile"; lite?: boolean };

export function Avatar(props: Props) {
  const [mode, setMode] = useState<"3d" | "2d">(() => (!props.lite && hasWebGL() ? "3d" : "2d"));
  return mode === "3d" ? <Avatar3D {...props} onFail={() => setMode("2d")} /> : <Avatar2D {...props} />;
}

function Avatar3D({ code, color, state, mouth, size = "stage", onFail }: Props & { onFail: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef<AvatarState>(state);
  live.current = state;
  const fail = useRef(onFail);
  fail.current = onFail;
  useEffect(() => {
    let stop = false;
    let raf = 0;
    let cleanup = () => {};
    loadThree().then((T) => {
      const el = host.current;
      if (stop || !el) return;
      const w = el.clientWidth || 320;
      const h = el.clientHeight || 320;
      const renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(w, h);
      el.appendChild(renderer.domElement);
      const scene = new T.Scene();
      const camera = new T.PerspectiveCamera(32, w / h, 0.1, 100);
      camera.position.set(0, 0.1, size === "stage" ? 7 : 6.2);
      const tint = new T.Color(color);
      scene.add(new T.AmbientLight(0xffffff, 0.55));
      const key = new T.DirectionalLight(0xffffff, 1.6);
      key.position.set(3, 4, 5);
      scene.add(key);
      const rim = new T.PointLight(tint, 18, 12);
      rim.position.set(-2.5, 1.5, -2.5);
      scene.add(rim);

      const rig = new T.Group();
      scene.add(rig);
      const skin = new T.MeshStandardMaterial({ color: tint.clone().lerp(new T.Color(0xffffff), 0.18), roughness: 0.32, metalness: 0.28 });
      const head = new T.Mesh(new T.IcosahedronGeometry(1.25, 5), skin);
      rig.add(head);
      // Signature visuelle par rôle.
      const extras: Three[] = [];
      if (code === "altair" || code === "orion") {
        const wire = new T.Mesh(new T.IcosahedronGeometry(1.48, 1), new T.MeshBasicMaterial({ color: tint, wireframe: true, transparent: true, opacity: 0.35 }));
        rig.add(wire);
        extras.push(wire);
      }
      const haloMat = new T.MeshStandardMaterial({ color: code === "maestro" ? 0xd4a63a : tint, emissive: code === "maestro" ? 0xb8860b : tint, emissiveIntensity: 0.6, metalness: 0.6, roughness: 0.25 });
      const halo = new T.Mesh(new T.TorusGeometry(1.78, 0.03, 16, 120), haloMat);
      halo.rotation.x = Math.PI / 2.3;
      rig.add(halo);
      if (code === "nova" || code === "vega" || code === "lyra") {
        const orbit = new T.Mesh(new T.TorusGeometry(1.95, 0.012, 8, 120), new T.MeshBasicMaterial({ color: tint, transparent: true, opacity: 0.55 }));
        orbit.rotation.set(Math.PI / 3, 0.4, 0);
        rig.add(orbit);
        extras.push(orbit);
      }
      // Visage.
      const white = new T.MeshStandardMaterial({ color: 0xffffff, roughness: 0.2 });
      const dark = new T.MeshStandardMaterial({ color: 0x0b1020, roughness: 0.4 });
      const eyes = [-0.42, 0.42].map((x) => {
        const eye = new T.Group();
        const ball = new T.Mesh(new T.SphereGeometry(0.2, 24, 24), white);
        const pupil = new T.Mesh(new T.SphereGeometry(0.1, 16, 16), dark);
        pupil.position.z = 0.13;
        eye.add(ball, pupil);
        eye.position.set(x, 0.26, 1.06);
        rig.add(eye);
        return eye;
      });
      const mouthMesh = new T.Mesh(new T.SphereGeometry(0.26, 24, 16), dark);
      mouthMesh.position.set(0, -0.42, 1.1);
      rig.add(mouthMesh);

      const clock = new T.Clock();
      let open = 0;
      let blink = 0;
      const loop = () => {
        raf = requestAnimationFrame(loop);
        const t = clock.getElapsedTime();
        const s = live.current;
        // Bouche : impulsions des mots + oscillation douce pendant la parole.
        const target = s === "speaking" ? Math.max(mouth.current, 0.25 + 0.3 * Math.abs(Math.sin(t * 13) * Math.sin(t * 4.7))) : 0;
        open += (target - open) * 0.35;
        mouth.current *= 0.88;
        mouthMesh.scale.set(1.5 - open * 0.4, 0.12 + open * 0.75, 0.45);
        // Clignement.
        if (Math.random() < 0.006) blink = 1;
        blink = Math.max(0, blink - 0.12);
        eyes.forEach((e) => (e.scale.y = 1 - Math.sin(blink * Math.PI) * 0.9));
        // Tête : respiration, écoute (inclinaison), parole (hochements).
        rig.position.y = Math.sin(t * 1.4) * 0.05;
        rig.rotation.y = Math.sin(t * 0.5) * 0.18 + (s === "listening" ? 0.12 : 0);
        rig.rotation.z = s === "listening" ? Math.sin(t * 0.8) * 0.05 + 0.06 : 0;
        rig.rotation.x = s === "speaking" ? Math.sin(t * 6) * 0.04 : Math.sin(t * 0.7) * 0.03;
        halo.rotation.z += s === "thinking" ? 0.06 : 0.008;
        haloMat.emissiveIntensity = s === "thinking" ? 0.9 + Math.sin(t * 8) * 0.5 : s === "speaking" ? 0.8 + open : 0.45;
        extras.forEach((x, i) => { x.rotation.y += 0.003 * (i + 1); x.rotation.x += 0.0015; });
        rim.intensity = 14 + (s === "speaking" ? 10 * open : 0);
        renderer.render(scene, camera);
      };
      loop();
      const ro = new ResizeObserver(() => {
        const nw = el.clientWidth || w;
        const nh = el.clientHeight || h;
        renderer.setSize(nw, nh);
        camera.aspect = nw / nh;
        camera.updateProjectionMatrix();
      });
      ro.observe(el);
      cleanup = () => {
        ro.disconnect();
        renderer.dispose();
        renderer.domElement.remove();
      };
    }).catch(() => !stop && fail.current());
    return () => {
      stop = true;
      cancelAnimationFrame(raf);
      cleanup();
    };
  }, [code, color, size, mouth]);
  return <div ref={host} className={`ac-avatar ac-avatar-${size} ac-st-${state}`} aria-hidden="true" />;
}

function Avatar2D({ color, state, mouth, size = "stage", name }: Props) {
  const mouthEl = useRef<SVGEllipseElement>(null);
  const live = useRef(state);
  live.current = state;
  useEffect(() => {
    let raf = 0;
    let open = 0;
    const loop = (ms: number) => {
      raf = requestAnimationFrame(loop);
      const t = ms / 1000;
      const target = live.current === "speaking" ? Math.max(mouth.current, 0.25 + 0.3 * Math.abs(Math.sin(t * 13))) : 0;
      open += (target - open) * 0.35;
      mouth.current *= 0.88;
      mouthEl.current?.setAttribute("ry", String(2 + open * 14));
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [mouth]);
  return (
    <div className={`ac-avatar ac-avatar-${size} ac-st-${state} ac-2d`} aria-hidden="true">
      <svg viewBox="0 0 200 200" role="img" aria-label={name}>
        <defs>
          <radialGradient id={`g-${name}`} cx="38%" cy="32%" r="70%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.85" />
            <stop offset="35%" stopColor={color} />
            <stop offset="100%" stopColor="#0b1020" />
          </radialGradient>
        </defs>
        <circle className="ac-halo2d" cx="100" cy="100" r="92" fill="none" stroke={color} strokeWidth="3" strokeDasharray="6 10" />
        <circle cx="100" cy="100" r="74" fill={`url(#g-${name})`} />
        <circle cx="76" cy="88" r="10" fill="#fff" />
        <circle cx="124" cy="88" r="10" fill="#fff" />
        <circle cx="78" cy="90" r="5" fill="#0b1020" />
        <circle cx="126" cy="90" r="5" fill="#0b1020" />
        <ellipse ref={mouthEl} cx="100" cy="128" rx="18" ry="2" fill="#0b1020" />
      </svg>
    </div>
  );
}
