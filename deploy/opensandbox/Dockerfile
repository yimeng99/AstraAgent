FROM python:3.11-slim
RUN pip install --no-cache-dir opensandbox-server==0.2.3
COPY patch_isolation.py /tmp/patch_isolation.py
RUN python /tmp/patch_isolation.py && rm /tmp/patch_isolation.py
EXPOSE 18080
ENTRYPOINT ["opensandbox-server"]
CMD ["--config", "/etc/opensandbox/config.toml"]
