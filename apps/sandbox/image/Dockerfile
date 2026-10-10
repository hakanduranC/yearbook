# Sandbox image for agent-written Python. Built as yearbook-sandbox:latest by image/build.sh.
# The image carries no network tooling and no package manager; the real boundary is the
# container configuration the service applies at run time (see README.md).
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    HOME=/tmp

# Pinned scientific stack. Bump deliberately; agent code is written against these versions.
RUN pip install --no-cache-dir \
      numpy==2.5.3 \
      pandas==3.0.6 \
      pillow==12.3.0 \
      matplotlib==3.11.2 \
 && pip uninstall -y pip setuptools wheel \
 && rm -rf /root/.cache \
 # Precompile: the root fs is read-only and PYTHONDONTWRITEBYTECODE is set, so without .pyc files
 # every run would compile numpy and pandas from source (measured: 5 s on 1 CPU).
 && python -m compileall -q -j 0 /usr/local/lib/python3.12

# Matplotlib builds its font cache on first import (3-5 s in an empty /tmp). Build it once here;
# sitecustomize.py copies it into MPLCONFIGDIR at interpreter start when that directory is empty.
RUN MPLCONFIGDIR=/opt/mpl python -c "import matplotlib.pyplot" \
 && chmod -R a+rX /opt/mpl
COPY sitecustomize.py /usr/local/lib/python3.12/site-packages/sitecustomize.py

# Non-root runner. The service also passes --user 10002:10002 explicitly so the image's
# USER line is a second line of defence, not the only one.
RUN groupadd --gid 10002 runner \
 && useradd --uid 10002 --gid 10002 --no-create-home --shell /usr/sbin/nologin runner \
 && mkdir -p /work && chown runner:runner /work

USER 10002:10002
WORKDIR /work
CMD ["python", "/work/main.py"]
