# =============================================================================
# Demucs Audio Separation Template for Vast.ai
# =============================================================================
# Image optimisee pour Vast.ai avec:
#   - PyTorch + CUDA (pre-cache sur Vast.ai)
#   - Demucs + ONNX Runtime GPU (packages compatibles Cloudflare)
#   - FFmpeg (conversion audio)
#   - CLI demucs-separate pour separation audio
#
# TAILLE IMAGE: ~6-7 GB
# PREMIER DEMARRAGE: +2 min pour extraction des modeles
#
# USAGE:
#   Sur Vast.ai: Selectionner ce template, lancer un pod GPU
#   Les modeles seront extraits automatiquement au premier demarrage
#
# CLI:
#   demucs-separate --input "https://url/audio.mp3" --output ./results
#   demucs-separate --input "https://url/audio.mp3" --interval-cut "300,600,900" --output ./results
#   demucs-separate --input "/path/to/local/audio.wav" --output ./results
#   demucs-separate --help
# =============================================================================

FROM vastai/pytorch:cuda-13.0.2-py311-auto

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
    ffmpeg \
    libsndfile1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# [2/7] PACKAGES COMPATIBLES CLOUDFLARE EN PREMIER
# =============================================================================
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
# [3/7] DEPENDANCES CRITIQUES
# =============================================================================
RUN pip install --no-cache-dir \
    scikit-learn \
    decorator \
    coloredlogs \
    flatbuffers \
    protobuf \
    fastapi \
    uvicorn \
    pydantic

# =============================================================================
# [4/7] COPIER LE DOSSIER MVSEP
# =============================================================================
WORKDIR /workspace

COPY mvsep/ /workspace/mvsep/

RUN cd /workspace/mvsep && \
    mkdir -p models results && \
    echo "Dossier mvsep copie"

# =============================================================================
# [5/7] TELECHARGER LES POIDS (SANS EXTRAIRE)
# =============================================================================
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
RUN DEMUCS_STATES=$(python3 -c "import demucs.states; print(demucs.states.__file__)" 2>/dev/null || echo "") && \
    if [ -n "$DEMUCS_STATES" ] && [ -f "$DEMUCS_STATES" ]; then \
        sed -i "s/torch.load(path, 'cpu')/torch.load(path, 'cpu', weights_only=False)/g" "$DEMUCS_STATES" 2>/dev/null && \
        echo "Patch PyTorch 2.6+ applique" || echo "Patch non necessaire ou deja applique"; \
    else \
        echo "demucs.states non trouve, patch ignore"; \
    fi

# =============================================================================
# [7/7] FIX COMPATIBILITE NUMPY/NUMBA
# =============================================================================
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

COPY demucs-separate /usr/local/bin/demucs-separate
RUN chmod +x /usr/local/bin/demucs-separate

COPY server.py /workspace/server.py

RUN mkdir -p /models-cache \
    && mkdir -p /root/.cache/torch/hub/checkpoints

WORKDIR /workspace/mvsep

EXPOSE 8185

CMD ["/start.sh"]
