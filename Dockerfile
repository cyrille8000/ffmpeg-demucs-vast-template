# =============================================================================
# FFmpeg + Demucs Template for Vast.ai
# =============================================================================
# Image optimisee pour Vast.ai avec:
#   - PyTorch + CUDA (pre-cache sur Vast.ai)
#   - JupyterLab
#   - FFmpeg (apt)
#   - Demucs + ONNX Runtime GPU (packages compatibles Cloudflare)
#   - CLI ffmpeg-demucs pour separation audio
#   - Poids des modeles (telecharges, extraction au premier demarrage)
#
# TAILLE IMAGE: ~6-7 GB
# PREMIER DEMARRAGE: +2 min pour extraction des modeles
#
# USAGE:
#   Sur Vast.ai: Selectionner ce template, lancer un pod GPU
#   Les modeles seront extraits automatiquement au premier demarrage
#
# CLI:
#   ffmpeg-demucs --input-url-youtube "https://..." --output ./results
#   ffmpeg-demucs --input-url-youtube "https://..." --file-cookie "https://url/cookies.txt" --output ./results
#   ffmpeg-demucs --input-url-youtube "https://..." --interval-cut "5.6,475.1,800.5" --output ./results
#   ffmpeg-demucs --input-file audio.mp3 --only-vocals --output ./results
#   ffmpeg-demucs --help
# =============================================================================

FROM vastai/pytorch:2.4.1-cuda-12.4.1-py311-22.04

SHELL ["/bin/bash", "-c"]

# =============================================================================
# VARIABLES D'ENVIRONNEMENT
# =============================================================================
ENV DEBIAN_FRONTEND=noninteractive
ENV BASE_URL="https://files.dubbingspark.com/b0e526cc7578d1e1986ae652f06fd499e22360f5/d5abd690f1c69f4a889039ddd4aa88d8"
ENV MODELS_EXTRACTED="false"

# =============================================================================
# [1/7] PACKAGES SYSTEME + FFMPEG
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    unzip \
    bc \
    ffmpeg \
    xz-utils \
    libsndfile1 \
    libopus0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# [2/7] PACKAGES COMPATIBLES CLOUDFLARE EN PREMIER
# =============================================================================
# IMPORTANT: Installer les packages Cloudflare AVANT pip pour eviter les conflits
# Ces packages contiennent:
#   - onnxruntime-gpu compatible CUDA 12.4
#   - numpy 1.x (requis par PyTorch 2.4)
#   - scipy, numba, etc. versions compatibles
RUN cd /tmp && \
    echo "Telechargement packages compatibles..." && \
    wget -q -O packages_compatibles.zip "$BASE_URL/packages_compatibles.zip" && \
    wget -q -O packages_python311.zip "$BASE_URL/packages_python311.zip" && \
    echo "Verification ZIP packages compatibles..." && \
    unzip -t packages_compatibles.zip > /dev/null 2>&1 || { echo "ZIP packages compatibles corrompu"; exit 1; } && \
    unzip -t packages_python311.zip > /dev/null 2>&1 || { echo "ZIP packages python311 corrompu"; exit 1; } && \
    echo "Extraction et installation packages compatibles..." && \
    unzip -q packages_compatibles.zip && \
    for pkg in temp_packages/compatible/*; do \
        if [ -f "$pkg" ]; then \
            pkg_name=$(basename "$pkg"); \
            echo "Installing: $pkg_name..."; \
            pip install "$pkg" --no-deps --force-reinstall 2>/dev/null || { \
                base_name=$(echo "$pkg_name" | cut -d'-' -f1); \
                echo "Echec pour $pkg_name, installation depuis PyPI: $base_name"; \
                pip install "$base_name"; \
            }; \
        fi; \
    done && \
    echo "Extraction et installation packages Python 3.11..." && \
    unzip -q packages_python311.zip && \
    for pkg in temp_packages/python311/*; do \
        if [ -f "$pkg" ]; then \
            pkg_name=$(basename "$pkg"); \
            echo "Installing: $pkg_name..."; \
            pip install "$pkg" --no-deps --force-reinstall 2>/dev/null || { \
                base_name=$(echo "$pkg_name" | cut -d'-' -f1); \
                echo "Echec pour $pkg_name, installation depuis PyPI: $base_name"; \
                pip install "$base_name"; \
            }; \
        fi; \
    done && \
    rm -rf /tmp/packages_*.zip /tmp/temp_packages && \
    echo "Packages compatibles installes"

# =============================================================================
# [3/7] DEPENDANCES CRITIQUES (exactement comme demucsServe.sh ligne 328)
# =============================================================================
# UNIQUEMENT ces 5 packages - demucs/librosa/soundfile sont dans Cloudflare
RUN pip install --no-cache-dir \
    scikit-learn \
    decorator \
    coloredlogs \
    flatbuffers \
    protobuf

# =============================================================================
# [4/7] COPIER LE DOSSIER MVSEP
# =============================================================================
WORKDIR /workspace

# Copier uniquement le dossier mvsep (pas de git clone pour eviter info sensibles)
COPY mvsep/ /workspace/mvsep/

RUN cd /workspace/mvsep && \
    mkdir -p models results && \
    echo "Dossier mvsep copie"

# =============================================================================
# [5/7] TELECHARGER LES POIDS (SANS EXTRAIRE)
# =============================================================================
# Les poids sont telecharges dans /workspace/model_weights/
# L'extraction se fait au premier demarrage via start.sh
RUN mkdir -p /workspace/model_weights && \
    cd /workspace/model_weights && \
    echo "Telechargement des poids des modeles (~2 GB)..." && \
    wget -q --show-progress -O models_part_aa "$BASE_URL/models_part_aa" && \
    wget -q --show-progress -O models_part_ab "$BASE_URL/models_part_ab" && \
    wget -q --show-progress -O models_part_ac "$BASE_URL/models_part_ac" && \
    echo "Poids telecharges (non extraits)"

# =============================================================================
# [6/7] PATCH PYTORCH 2.6+ COMPATIBILITE
# =============================================================================
RUN DEMUCS_STATES=$(python3 -c "import demucs.states; print(demucs.states.__file__)" 2>/dev/null) && \
    if [ -n "$DEMUCS_STATES" ] && [ -f "$DEMUCS_STATES" ]; then \
        sed -i "s/torch.load(path, 'cpu')/torch.load(path, 'cpu', weights_only=False)/g" "$DEMUCS_STATES" && \
        echo "Patch PyTorch 2.6+ applique"; \
    fi

# =============================================================================
# [7/7] FIX COMPATIBILITE NUMPY/NUMBA (demucsServe.sh lignes 338-352)
# =============================================================================
# Numba requiert NumPy < 2.3 - downgrade si necessaire
RUN echo "Verification compatibilite NumPy/Numba..." && \
    NUMPY_VERSION=$(python3 -c "import numpy; print(numpy.__version__)" 2>/dev/null) && \
    echo "NumPy actuel: $NUMPY_VERSION" && \
    if python3 -c "import numpy; exit(0 if tuple(map(int, numpy.__version__.split('.')[:2])) >= (2, 3) else 1)" 2>/dev/null; then \
        echo "NumPy >= 2.3 detecte, downgrade vers version compatible..." && \
        pip install "numpy<2.3" --force-reinstall && \
        echo "NumPy downgrade: $(python3 -c 'import numpy; print(numpy.__version__)')"; \
    else \
        echo "NumPy $NUMPY_VERSION compatible avec Numba"; \
    fi

# =============================================================================
# SCRIPTS ET CONFIGURATION
# =============================================================================
COPY start.sh /start.sh
RUN chmod +x /start.sh

# CLI ffmpeg-demucs (outil en ligne de commande)
COPY ffmpeg-demucs /usr/local/bin/ffmpeg-demucs
RUN chmod +x /usr/local/bin/ffmpeg-demucs

# Creer les repertoires pour les modeles
RUN mkdir -p /models-cache \
    && mkdir -p /root/.cache/torch/hub/checkpoints

WORKDIR /workspace/mvsep

EXPOSE 8888 8185

# =============================================================================
# ENTRYPOINT
# =============================================================================
# Au demarrage:
# 1. Extrait les modeles si pas deja fait
# 2. Lance JupyterLab
CMD ["/start.sh"]
