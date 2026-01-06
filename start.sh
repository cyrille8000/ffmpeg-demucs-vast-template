#!/bin/bash
# =============================================================================
# START.SH - Script de demarrage Vast.ai
# =============================================================================
# 1. Verifie GPU
# 2. Extrait les modeles ML si pas deja fait
# 3. Verifie packages Python
# 4. Installe yt-dlp (pour le CLI ffmpeg-demucs)
# 5. Lance JupyterLab
# =============================================================================

set -e

echo "=============================================="
echo "  FFMPEG + DEMUCS VAST.AI TEMPLATE"
echo "=============================================="
echo ""

# =============================================================================
# [1/4] VERIFICATION GPU
# =============================================================================
echo "[1/4] Verification GPU..."

if command -v nvidia-smi &> /dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | xargs)
    VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | xargs)
    echo "  GPU: $GPU_NAME"
    echo "  VRAM: ${VRAM} MB"
else
    echo "  GPU non detecte"
fi
echo ""

# =============================================================================
# [2/4] EXTRACTION DES MODELES (si necessaire)
# =============================================================================
echo "[2/4] Verification des modeles ML..."

MODELS_CACHE="/models-cache"
MVSEP_MODELS="/workspace/mvsep/models"
TORCH_CHECKPOINTS="$HOME/.cache/torch/hub/checkpoints"
WEIGHTS_DIR="/workspace/model_weights"

# Verifier si les modeles sont deja extraits
if [ -f "$MODELS_CACHE/Kim_Vocal_2.onnx" ] && [ -f "$MODELS_CACHE/04573f0d-f3cf25b2.th" ]; then
    echo "  Modeles deja extraits"
else
    echo "  Extraction des modeles (~2 GB)..."
    echo "  Cela peut prendre 1-2 minutes..."

    cd "$WEIGHTS_DIR"

    # Reconstituer et extraire les modeles
    echo "  Reconstitution du ZIP..."
    cat models_part_* > models_complete.zip

    echo "  Extraction..."
    unzip -q models_complete.zip -d temp_models/

    # Creer les repertoires
    mkdir -p "$MODELS_CACHE"
    mkdir -p "$MVSEP_MODELS"
    mkdir -p "$TORCH_CHECKPOINTS"

    # Copier les modeles
    echo "  Placement des modeles..."

    # Modeles ONNX (MVSEP)
    cp temp_models/Kim_Vocal_2.onnx "$MODELS_CACHE/" 2>/dev/null || true
    cp temp_models/Kim_Inst.onnx "$MODELS_CACHE/" 2>/dev/null || true

    # Modeles PyTorch (Demucs)
    for model in temp_models/*.th; do
        [ -f "$model" ] && cp "$model" "$MODELS_CACHE/"
        [ -f "$model" ] && cp "$model" "$TORCH_CHECKPOINTS/"
    done

    # Symlinks pour MVSEP (ONNX models)
    for model in "$MODELS_CACHE"/*.onnx; do
        [ -f "$model" ] && ln -sf "$model" "$MVSEP_MODELS/$(basename "$model")" 2>/dev/null || true
    done

    # Symlinks pour Demucs (.th models) vers MVSEP et torch hub
    for model in "$MODELS_CACHE"/*.th; do
        [ -f "$model" ] && ln -sf "$model" "$MVSEP_MODELS/$(basename "$model")" 2>/dev/null || true
        [ -f "$model" ] && ln -sf "$model" "$TORCH_CHECKPOINTS/$(basename "$model")" 2>/dev/null || true
    done

    # Nettoyer
    rm -f models_complete.zip
    rm -rf temp_models/

    echo "  Modeles extraits"
fi

MODEL_COUNT=$(ls "$MODELS_CACHE"/*.onnx "$MODELS_CACHE"/*.th 2>/dev/null | wc -l)
echo "  $MODEL_COUNT modeles disponibles"
echo ""

# =============================================================================
# [3/5] VERIFICATION PACKAGES PYTHON
# =============================================================================
echo "[3/5] Verification packages Python..."

# Les packages sont deja installes dans l'image Docker
if python3 -c "import onnxruntime; import demucs" 2>/dev/null; then
    echo "  Packages Python OK"
else
    echo "  ERREUR: Packages Python manquants!"
    echo "  Verifiez que l'image Docker a ete correctement construite."
fi
echo ""

# =============================================================================
# [4/5] TELECHARGEMENT YT-DLP (derniere version)
# =============================================================================
echo "[4/5] Installation yt-dlp..."

YTDLP_PATH="/usr/local/bin/yt-dlp"

if [ -x "$YTDLP_PATH" ]; then
    YTDLP_VERSION=$("$YTDLP_PATH" --version 2>/dev/null)
    echo "  yt-dlp deja installe: $YTDLP_VERSION"
else
    if wget -q -O "$YTDLP_PATH" "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp" 2>/dev/null; then
        chmod +x "$YTDLP_PATH"
        YTDLP_VERSION=$("$YTDLP_PATH" --version 2>/dev/null)
        echo "  yt-dlp installe: $YTDLP_VERSION"
    else
        echo "  ATTENTION: Echec installation yt-dlp"
        echo "  Le CLI ffmpeg-demucs ne pourra pas telecharger depuis YouTube"
    fi
fi
echo ""

# =============================================================================
# [5/5] LANCEMENT JUPYTERLAB
# =============================================================================
echo "[5/5] Lancement JupyterLab..."
echo ""
echo "=============================================="
echo "  PRET !"
echo "=============================================="
echo ""
echo "  JupyterLab: http://localhost:8888"
echo "  Repertoire: /workspace/mvsep"
echo ""
echo "  CLI ffmpeg-demucs (recommande):"
echo "    ffmpeg-demucs --input-url-youtube 'https://...' --output ./results"
echo "    ffmpeg-demucs --input-url-youtube 'https://...' --file-cookie 'https://url/cookies.txt' --output ./results"
echo "    ffmpeg-demucs --input-url-youtube 'https://...' --interval-cut '5.6,475.1,800.5' --output ./results"
echo "    ffmpeg-demucs --input-file audio.mp3 --only-vocals --output ./results"
echo "    ffmpeg-demucs --help"
echo ""
echo "  Ou directement avec Python:"
echo "    cd /workspace/mvsep"
echo "    python3 inference_demucs.py --input_audio votre_audio.mp3 --output_folder ./results --only_vocals"
echo ""

cd /workspace

# Lancer JupyterLab (Vast.ai s'attend a ca)
jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root --NotebookApp.token='' --NotebookApp.password=''
