#!/bin/bash
# =============================================================================
# START.SH - Script de demarrage Vast.ai
# =============================================================================
# 1. Verifie GPU
# 2. Extrait les modeles ML si pas deja fait
# 3. Verifie packages Python
# 4. Lance JupyterLab
# =============================================================================

set -e

echo "=============================================="
echo "  DEMUCS AUDIO SEPARATION - VAST.AI"
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

if [ -f "$MODELS_CACHE/Kim_Vocal_2.onnx" ] && [ -f "$MODELS_CACHE/04573f0d-f3cf25b2.th" ]; then
    echo "  Modeles deja extraits"
else
    echo "  Extraction des modeles (~2 GB)..."
    echo "  Cela peut prendre 1-2 minutes..."

    cd "$WEIGHTS_DIR"

    echo "  Reconstitution du ZIP..."
    cat models_part_* > models_complete.zip

    echo "  Extraction..."
    unzip -q models_complete.zip -d temp_models/

    mkdir -p "$MODELS_CACHE"
    mkdir -p "$MVSEP_MODELS"
    mkdir -p "$TORCH_CHECKPOINTS"

    echo "  Placement des modeles..."

    cp temp_models/Kim_Vocal_2.onnx "$MODELS_CACHE/" 2>/dev/null || true
    cp temp_models/Kim_Inst.onnx "$MODELS_CACHE/" 2>/dev/null || true

    for model in temp_models/*.th; do
        [ -f "$model" ] && cp "$model" "$MODELS_CACHE/"
        [ -f "$model" ] && cp "$model" "$TORCH_CHECKPOINTS/"
    done

    for model in "$MODELS_CACHE"/*.onnx; do
        [ -f "$model" ] && ln -sf "$model" "$MVSEP_MODELS/$(basename "$model")" 2>/dev/null || true
    done

    for model in "$MODELS_CACHE"/*.th; do
        [ -f "$model" ] && ln -sf "$model" "$MVSEP_MODELS/$(basename "$model")" 2>/dev/null || true
        [ -f "$model" ] && ln -sf "$model" "$TORCH_CHECKPOINTS/$(basename "$model")" 2>/dev/null || true
    done

    rm -f models_complete.zip
    rm -rf temp_models/

    echo "  Modeles extraits"
fi

MODEL_COUNT=$(ls "$MODELS_CACHE"/*.onnx "$MODELS_CACHE"/*.th 2>/dev/null | wc -l)
echo "  $MODEL_COUNT modeles disponibles"
echo ""

# =============================================================================
# [3/4] VERIFICATION PACKAGES PYTHON
# =============================================================================
echo "[3/4] Verification packages Python..."

if python3 -c "import onnxruntime; import demucs" 2>/dev/null; then
    echo "  Packages Python OK"
else
    echo "  ERREUR: Packages Python manquants!"
fi
echo ""

# =============================================================================
# [4/5] INSTALLATION DEPENDENCIES SERVEUR
# =============================================================================
echo "[4/5] Installation dependencies serveur..."

pip install --quiet fastapi uvicorn pydantic 2>/dev/null || echo "  Dependencies deja installees"
echo ""

# =============================================================================
# [5/5] LANCEMENT DES SERVICES
# =============================================================================
echo "[5/5] Lancement des services..."
echo ""
echo "=============================================="
echo "  PRET !"
echo "=============================================="
echo ""
echo "  API Demucs:   http://localhost:8185"
echo "  JupyterLab:   http://localhost:8888"
echo "  Repertoire:   /workspace/mvsep"
echo ""
echo "  Endpoints API:"
echo "    POST /job          - Creer un job de separation"
echo "    GET  /job/{id}     - Statut du job"
echo "    GET  /result/{id}  - Telecharger le resultat"
echo "    GET  /health       - Health check"
echo "    GET  /status       - Statut serveur"
echo ""
echo "  CLI demucs-separate:"
echo "    demucs-separate --input 'https://url/audio.mp3' --output ./results"
echo "    demucs-separate --input 'https://...' --interval-cut '300,600,900' --output ./results"
echo "    demucs-separate --input /path/to/audio.wav --output ./results"
echo "    demucs-separate --help"
echo ""

cd /workspace

# Copier le serveur si il n'existe pas encore
if [ ! -f /workspace/server.py ]; then
    cp /workspace/mvsep/../server.py /workspace/server.py 2>/dev/null || true
fi

# Lancer le serveur API en background
python3 /workspace/server.py &
API_PID=$!
echo "  Serveur API demarre (PID: $API_PID)"

# Lancer JupyterLab en foreground
jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root --NotebookApp.token='' --NotebookApp.password=''
