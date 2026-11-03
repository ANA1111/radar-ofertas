FROM python:3.12-slim
WORKDIR /app
COPY app.py /app/app.py
RUN useradd --create-home --uid 10001 radar
USER radar
CMD ["python", "-u", "app.py", "dry-run"]
