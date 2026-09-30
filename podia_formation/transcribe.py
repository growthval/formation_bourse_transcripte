"""Transcription locale en français avec faster-whisper (Whisper d'OpenAI).

Réglages orientés qualité :
- modèle large-v3 (ou le large-v3 affiné pour le français, ``--modele francais``) ;
- langue forcée, recherche en faisceau (beam 5), filtre des silences (VAD) ;
- un contexte en français (initial_prompt) et des « mots-clés » (hotwords) rappelés à Whisper
  sur toute la durée de la vidéo : titre de la leçon et termes boursiers difficiles ;
- filtre des hallucinations connues de Whisper en français et des boucles de répétition.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .text import format_duration, timestamp

DEFAULT_MODEL = "large-v3"
# Modèles hébergés hors du catalogue de faster-whisper : (dépôt Hugging Face, sous-dossier CTranslate2).
PRESETS = {"francais": ("bofenghuang/whisper-large-v3-french", "ctranslate2")}

CONTEXTE = ("Transcription d'une formation vidéo en français sur l'investissement en bourse : actions, "
            "obligations, ETF, PEA, compte-titres, assurance-vie, dividendes, rendement, capitalisation, "
            "CAC 40, analyse fondamentale et analyse technique.")
# Termes difficiles rappelés à chaque fenêtre de 30 s (budget limité : ~50 jetons avec le titre).
TERMES_CLES = ["Zonebourse", "PEA-PME", "ETF", "CAC 40", "SBF 120", "MSCI World", "S&P 500", "OPCVM",
               "SICAV", "BPA", "EBITDA", "PER", "dividendes", "obligations", "courtier"]
PROMPT_MAX_TOKENS = 150
HOTWORDS_MAX_TOKENS = 50

# Phrases que Whisper invente sur les silences ou la musique (vues sur des corpus français).
# Génériques de sous-titrage : jamais prononcés dans un cours, retirés où qu'ils soient.
HALLUCINATIONS = re.compile(
    r"sous-titr\w*.{0,40}(radio-canada|amara|st'? ?501|soustitreur)|amara\.org|sous-titres réalisés", re.I)
# Formules de fin de vidéo YouTube : retirées seulement quand elles forment tout le segment
# (« abonnez-vous à la version Premium de Zonebourse » est une vraie phrase du cours).
HALLUCINATIONS_SEULES = re.compile(
    r"(merci d'avoir regardé( cette vidéo)?|abonnez-vous( à la chaîne)?|"
    r"n'oubliez pas de (vous abonner|liker|mettre un pouce)( bleu)?)( et à bientôt)?", re.I)


@dataclass
class Segment:
    start: float
    end: float
    text: str
    avg_logprob: float = 0.0
    compression_ratio: float = 1.0


# --- Contexte donné à Whisper -------------------------------------------------

def _approx_tokens(text: str) -> int:
    return len(text) // 3 + 1


def build_prompt(course: str, module: str, lesson: str, user_terms: list[str] | None = None,
                 count_tokens: Callable[[str], int] = _approx_tokens) -> tuple[str, str, list[str]]:
    """(initial_prompt, hotwords, termes écartés faute de place).

    faster-whisper ne garde que la FIN du prompt (223 jetons) : le contexte propre à la leçon est
    donc placé à la fin. Les hotwords sont réinjectés à chaque fenêtre mais prennent de la place à
    la génération : on les limite à ~50 jetons.
    """
    module_part = module if re.match(r"(?i)module\s*\d+", module or "") else (f"Module : {module}" if module else "")
    tail = " ".join(p for p in (f"Formation « {course} »." if course else "",
                                f"{module_part}." if module_part else "",
                                f"Leçon : « {lesson} »." if lesson else "") if p)
    prompt = f"{CONTEXTE} {tail}".strip()
    if count_tokens(prompt) > PROMPT_MAX_TOKENS:
        prompt = tail
    terms = list(dict.fromkeys([*(user_terms or []), *TERMES_CLES]))
    dropped: list[str] = []
    head = f"{lesson}." if lesson else ""
    while terms and count_tokens(f"{head} {', '.join(terms)}") > HOTWORDS_MAX_TOKENS:
        dropped.append(terms.pop())
    hotwords = f"{head} {', '.join(terms)}".strip()
    dropped = [t for t in dropped if t in (user_terms or [])]
    return prompt, hotwords, dropped


def read_terms(path: str | Path) -> list[str]:
    """Fichier de vocabulaire (un terme par ligne), en UTF-8 ou en ANSI Windows."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return list(dict.fromkeys(t.strip() for t in text.splitlines() if t.strip()))


# --- Modèle et matériel ---------------------------------------------------------

def _preload_cuda_dlls() -> None:
    """Rend visibles les bibliothèques CUDA installées par pip (nvidia-cublas-cu12, nvidia-cudnn-cu12)."""
    import ctypes
    import site

    if sys.platform.startswith("linux"):
        for root in [*site.getsitepackages(), site.getusersitepackages()]:
            for sub in ("cuda_runtime", "cublas", "cudnn"):
                libs = sorted(Path(root, "nvidia", sub, "lib").glob("*.so*"), key=lambda f: "Lt" not in f.name)
                for lib in libs:
                    try:
                        ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass
        return
    if sys.platform != "win32":
        return

    roots = [*site.getsitepackages(), site.getusersitepackages()]
    for root in roots:
        for sub in ("cublas", "cudnn", "cuda_runtime"):
            d = Path(root, "nvidia", sub, "bin")
            if not d.is_dir():
                continue
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            for dll in d.glob("*.dll"):
                try:
                    ctypes.CDLL(str(dll))
                except OSError:
                    pass


def cpu_threads() -> int:
    """Cœurs physiques estimés (CTranslate2 n'en utilise que 4 par défaut)."""
    try:
        import psutil
        n = psutil.cpu_count(logical=False)
        if n:
            return n
    except Exception:
        pass
    logical = os.cpu_count() or 4
    return max(1, logical // 2 if logical >= 8 else logical)


def ensure_model(name: str, log: Callable[[str], None] = print) -> str:
    """Chemin local du modèle, téléchargé au besoin avec une barre de progression."""
    if Path(name).is_dir():
        return name
    from huggingface_hub import snapshot_download

    if name in PRESETS:
        repo, sub = PRESETS[name]
        log(f"Modèle « {name} » ({repo}) : téléchargement d'environ 3 Go au premier lancement...")
        return str(Path(snapshot_download(repo, allow_patterns=[f"{sub}/*"])) / sub)
    from faster_whisper.utils import _MODELS

    repo = _MODELS.get(name, name)
    size = {"large-v3": "3 Go", "large-v3-turbo": "1,6 Go", "turbo": "1,6 Go", "medium": "1,5 Go", "small": "500 Mo"}
    log(f"Modèle « {name} » : téléchargement d'environ {size.get(name, 'quelques Go')} au premier lancement "
        "(reprend là où il s'est arrêté si interrompu)...")
    return snapshot_download(repo, allow_patterns=["config.json", "preprocessor_config.json", "model.bin",
                                                   "tokenizer.json", "vocabulary.*"])


# Essai réel dans un processus séparé (une bibliothèque CUDA manquante peut faire planter le processus) :
# 30 s de bruit, sans filtre de silence, pour solliciter l'encodeur et la recherche en faisceau.
_SMOKE = """
import sys
sys.path.insert(0, {pkg!r})
from podia_formation.transcribe import _preload_cuda_dlls
_preload_cuda_dlls()
import numpy as np
from faster_whisper import WhisperModel
m = WhisperModel({path!r}, device="cuda", compute_type={ct!r})
audio = np.random.default_rng(0).normal(0, 0.02, 16000 * 30).astype(np.float32)
list(m.transcribe(audio, language="fr", vad_filter=False, beam_size={beam}, word_timestamps=True)[0])
"""


def gpu_memory_mb() -> int | None:
    """Mémoire de la carte NVIDIA (via nvidia-smi, installé avec le pilote)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout
        return max(int(float(x)) for x in out.split() if x.strip())
    except Exception:
        return None


def gpu_compute_types(supported: set[str], memory_mb: int | None) -> list[str]:
    """Précisions à essayer, de la meilleure à la plus sûre.

    large-v3 en float16 demande ~4,5 Go avec beam 5 : sur une carte de 4 Go (GTX 1650…),
    on commence par int8_float16 (~3 Go, perte de précision négligeable).
    """
    if memory_mb is not None and memory_mb < 6000:
        order = ["int8_float16", "int8", "int8_float32"]
    else:
        order = ["float16", "int8_float16", "int8"]
    return [t for t in order if t in supported] or ["default"]


def select_device(requested: str, model_path: str, precision: str = "",
                  log: Callable[[str], None] = print, beam_size: int = 5) -> tuple[str, str]:
    """(appareil, précision). Le GPU n'est retenu qu'après un essai réel réussi."""
    cpu = ("cpu", precision or "int8")
    if requested == "cpu":
        return cpu
    _preload_cuda_dlls()
    try:
        import ctranslate2
        count = ctranslate2.get_cuda_device_count()
        types = ctranslate2.get_supported_compute_types("cuda") if count else set()
    except Exception:
        count, types = 0, set()
    if not count:
        if requested == "cuda":
            log("ATTENTION : Aucun GPU NVIDIA utilisable : calcul sur le processeur.")
        return cpu
    memory = gpu_memory_mb()
    candidates = [precision] if precision else gpu_compute_types(set(types), memory)
    pkg = str(Path(__file__).resolve().parent.parent)
    detail: list[str] = []
    for ct in candidates:
        log(f"Essai du GPU ({f'{memory / 1024:.1f} Go, ' if memory else ''}précision {ct})...")
        try:
            proc = subprocess.run([sys.executable, "-c", _SMOKE.format(pkg=pkg, path=model_path, ct=ct, beam=beam_size)],
                                  capture_output=True, text=True, errors="replace", timeout=1800)
            if proc.returncode == 0:
                return "cuda", ct
            detail = (proc.stderr or "").strip().splitlines()[-1:]
        except Exception as exc:
            detail = [str(exc)]
    log("ATTENTION : Le GPU est inutilisable (bibliothèques CUDA 12 / cuDNN 9 absentes, carte trop ancienne ou "
        f"mémoire insuffisante) : calcul sur le processeur. {' '.join(detail)}")
    return cpu


def load_model(name: str = DEFAULT_MODEL, device: str = "auto", precision: str = "",
               threads: int = 0, log: Callable[[str], None] = print, beam_size: int = 5):
    """(modèle, appareil)."""
    try:
        import importlib
        importlib.import_module("onnxruntime")   # filtre des silences : échoue aussi sans le composant Visual C++
        from faster_whisper import WhisperModel
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "Impossible de charger Whisper. Sous Windows, installez le composant Microsoft « Visual C++ "
            "Redistributable x64 » (https://aka.ms/vs/17/release/vc_redist.x64.exe), puis relancez. "
            f"Détail : {exc}") from exc

    path = ensure_model(name, log)
    device, compute_type = select_device(device, path, precision, log, beam_size)
    if device == "cuda":
        log(f"GPU retenu (précision {compute_type}).")
    kwargs = {"cpu_threads": threads or cpu_threads()} if device == "cpu" else {}
    return WhisperModel(path, device=device, compute_type=compute_type, **kwargs), device


def token_counter(model) -> Callable[[str], int]:
    tok = getattr(model, "hf_tokenizer", None)
    if tok is None:
        return _approx_tokens
    return lambda text: len(tok.encode(" " + text).ids)


# --- Nettoyage et mise en forme ----------------------------------------------------

def _key(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


def clean_segments(segments: Iterable[Segment]) -> list[Segment]:
    """Retire les segments vides, les hallucinations connues et les boucles de répétition."""
    out: list[Segment] = []
    keys: list[str] = []
    for seg in segments:
        text = " ".join(seg.text.split())
        key = _key(text)
        if not key or HALLUCINATIONS.search(text) or seg.compression_ratio > 2.4:
            continue
        if HALLUCINATIONS_SEULES.fullmatch(text.strip(" .!?…,")):
            continue
        if keys and key == keys[-1]:
            continue                                   # « Merci. » / « Merci ! »
        if len(keys) >= 3 and key == keys[-2] and keys[-1] == keys[-3]:
            continue                                   # boucle A B A B
        keys.append(key)
        out.append(Segment(seg.start, seg.end, text, seg.avg_logprob, seg.compression_ratio))
    return out


def _ends_sentence(text: str) -> bool:
    return text.rstrip().rstrip("»\"”’) ").endswith((".", "!", "?", "…"))


def paragraphs(segments: list[Segment], max_seconds: float = 75.0, pause: float = 1.5) -> list[tuple[float, str]]:
    """Regroupe les segments en paragraphes lisibles (pause marquée ou fin de phrase après ~1 min)."""
    paras: list[tuple[float, str]] = []
    current: list[Segment] = []
    for seg in segments:
        if current:
            gap = seg.start - current[-1].end
            ends = _ends_sentence(current[-1].text)
            long_enough = seg.start - current[0].start >= max_seconds
            too_long = seg.start - current[0].start >= 2 * max_seconds or sum(len(s.text) + 1 for s in current) > 1200
            if (gap >= pause and ends) or (long_enough and ends) or gap >= 4 or too_long:
                paras.append((current[0].start, " ".join(s.text for s in current)))
                current = []
        current.append(seg)
    if current:
        paras.append((current[0].start, " ".join(s.text for s in current)))
    return paras


def output_paths(dest_stem: Path) -> list[Path]:
    return [dest_stem.with_name(dest_stem.name + ext) for ext in (".txt", ".md", ".srt")]


def write_outputs(segments: list[Segment], dest_stem: Path, title: str, source_url: str,
                  duration: float | None) -> list[Path]:
    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    txt, md, srt = output_paths(dest_stem)
    paras = paragraphs(segments)
    txt.write_text("\n\n".join(p for _, p in paras) + "\n", encoding="utf-8")
    md_lines = [f"# {title}", "", f"Source : {source_url}  ", f"Durée : {format_duration(duration)}", ""]
    md_lines += [f"**[{timestamp(start)}]** {p}\n" for start, p in paras]
    md.write_text("\n".join(md_lines), encoding="utf-8")
    srt_lines = []
    for i, seg in enumerate(segments, start=1):
        srt_lines += [str(i), f"{timestamp(seg.start, True)} --> {timestamp(seg.end, True)}", seg.text, ""]
    srt.write_text("\n".join(srt_lines), encoding="utf-8")     # écrit en dernier : marque la fin
    return [txt, md, srt]


def is_transcribed(dest_stem: Path, audio: Path) -> bool:
    files = output_paths(dest_stem)
    return all(p.is_file() for p in files) and files[-1].stat().st_mtime >= audio.stat().st_mtime


def transcribe_file(model, audio: Path, prompt: str, hotwords: str = "", log: Callable[[str], None] = print,
                    beam_size: int = 5) -> tuple[list[Segment], float | None]:
    segments, info = model.transcribe(
        str(audio),
        language="fr",
        task="transcribe",
        beam_size=beam_size,
        best_of=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 400},
        condition_on_previous_text=True,
        initial_prompt=prompt,
        hotwords=hotwords or None,
        word_timestamps=True,
        hallucination_silence_threshold=2.0,
    )
    total = getattr(info, "duration", None) or 0
    out: list[Segment] = []
    started = time.monotonic()
    last_report = 0.0
    for seg in segments:
        out.append(Segment(seg.start, seg.end, seg.text, getattr(seg, "avg_logprob", 0.0),
                           getattr(seg, "compression_ratio", 1.0)))
        now = time.monotonic()
        if total and now - last_report > 20:
            last_report = now
            log(f"      {seg.end / total:5.0%} ({format_duration(seg.end)} / {format_duration(total)}, "
                f"{format_duration(now - started)} écoulées)")
    cleaned = clean_segments(out)
    spoken = sum(s.end - s.start for s in cleaned)
    if total > 60 and spoken < 0.3 * total:
        log("      ATTENTION : transcription très courte par rapport à la durée : vérifiez le fichier audio.")
    return cleaned, (total or None)


def vtt_to_text(path: Path) -> str:
    """Texte brut d'un fichier de sous-titres WebVTT (sans horodatages ni balises)."""
    lines, last = [], ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit() or line.startswith(("NOTE", "STYLE", "X-TIMESTAMP")):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line != last:
            lines.append(line)
            last = line
    return " ".join(lines)
