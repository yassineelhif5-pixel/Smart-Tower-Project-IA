/** Dépôt de fichiers sur un projet et OCR gratuit dans le navigateur (Tesseract.js ; pdf.js pour les PDF scannés). */
import { API_BASE, ApiError } from "../../api/client";

export type UploadedDoc = {
  id: string; name: string; ext: string; type: string; typeLabel?: string; version: number; clientVisible: boolean;
  notified?: number; mailed?: number; extraction?: { words?: number; source?: string } & Record<string, unknown>;
};

function readCookie(name: string) {
  return document.cookie.split("; ").find((c) => c.startsWith(`${name}=`))?.split("=")[1];
}

/** POST multipart /projects/<id>/documents (le client JSON de l'application ne gère pas les fichiers). */
export async function uploadProjectFile(projectId: string, file: File, fields: Record<string, string> = {}): Promise<UploadedDoc> {
  if (!readCookie("csrftoken")) await fetch(`${API_BASE}/auth/csrf`, { credentials: "same-origin" });
  const fd = new FormData();
  fd.append("file", file);
  Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
  const r = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/documents`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRFToken": decodeURIComponent(readCookie("csrftoken") ?? "") },
    body: fd,
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, body);
  return body as UploadedDoc;
}

/** Fichier d'un document déjà déposé (pour l'OCR après coup). */
export async function fetchDocBlob(projectId: string, docId: string): Promise<Blob> {
  const r = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}`, {
    credentials: "same-origin",
  });
  if (!r.ok) throw new Error("Fichier indisponible");
  return r.blob();
}

type Img = Blob | HTMLCanvasElement;
type TesseractLike = {
  recognize: (f: Img, lang: string, o: { logger: (m: { status: string; progress: number }) => void }) => Promise<{ data: { text: string } }>;
};
let tesseract: Promise<TesseractLike> | null = null;
export function loadTesseract(): Promise<TesseractLike> {
  tesseract ??= new Promise((resolve, reject) => {
    const w = window as unknown as { Tesseract?: TesseractLike };
    if (w.Tesseract) return resolve(w.Tesseract);
    const sc = document.createElement("script");
    sc.src = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";
    sc.onload = () => (w.Tesseract ? resolve(w.Tesseract) : reject(new Error("OCR indisponible")));
    sc.onerror = () => { tesseract = null; reject(new Error("OCR indisponible (pas d'accès au CDN)")); };
    document.head.appendChild(sc);
  });
  return tesseract;
}

type PdfJs = {
  GlobalWorkerOptions: { workerSrc: string };
  getDocument: (src: { data: ArrayBuffer }) => { promise: Promise<{
    numPages: number;
    getPage: (n: number) => Promise<{
      getViewport: (o: { scale: number }) => { width: number; height: number };
      render: (o: { canvasContext: CanvasRenderingContext2D; viewport: unknown }) => { promise: Promise<void> };
    }>;
  }> };
};
const PDFJS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/";
let pdfjs: Promise<PdfJs> | null = null;
function loadPdfJs(): Promise<PdfJs> {
  pdfjs ??= (import(/* @vite-ignore */ `${PDFJS}pdf.min.mjs`) as Promise<PdfJs>).then((m) => {
    m.GlobalWorkerOptions.workerSrc = `${PDFJS}pdf.worker.min.mjs`;
    return m;
  }).catch((e) => { pdfjs = null; throw e; });
  return pdfjs;
}

export const MAX_OCR_PAGES = 12;

/** Texte reconnu d'une image ou d'un PDF (pages rendues puis lues par OCR). `onProgress` reçoit un libellé. */
export async function ocrFile(file: Blob, name: string, onProgress: (label: string) => void): Promise<string> {
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(name);
  const isImg = file.type.startsWith("image/") || /\.(png|jpe?g|gif|bmp|webp|tiff?)$/i.test(name);
  if (!isPdf && !isImg) throw new Error("L'OCR ne s'applique qu'aux images et aux PDF.");
  onProgress("Chargement de l'OCR…");
  const T = await loadTesseract();
  if (isImg) {
    const res = await T.recognize(file, "fra+eng", {
      logger: (m) => m.status === "recognizing text" && onProgress(`Lecture du texte (OCR)… ${Math.round(m.progress * 100)} %`),
    });
    return res.data.text;
  }
  onProgress("Ouverture du PDF…");
  const lib = await loadPdfJs();
  const pdf = await lib.getDocument({ data: await file.arrayBuffer() }).promise;
  const pages = Math.min(pdf.numPages, MAX_OCR_PAGES);
  const out: string[] = [];
  for (let n = 1; n <= pages; n++) {
    const page = await pdf.getPage(n);
    const viewport = page.getViewport({ scale: 2 });
    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) break;
    await page.render({ canvasContext: ctx, viewport }).promise;
    const res = await T.recognize(canvas, "fra+eng", {
      logger: (m) => m.status === "recognizing text" &&
        onProgress(`OCR page ${n}/${pages}… ${Math.round(m.progress * 100)} %`),
    });
    out.push(res.data.text);
  }
  return out.join("\n");
}

export const isOcrable = (name: string, mime = "") =>
  /\.(pdf|png|jpe?g|gif|bmp|webp|tiff?)$/i.test(name) || mime.startsWith("image/") || mime === "application/pdf";
