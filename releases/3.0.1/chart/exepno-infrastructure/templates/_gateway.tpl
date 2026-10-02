{{- define "exepno.gatewayConfig" -}}
pid /tmp/nginx.pid;
events { worker_connections 512; }
http {
  access_log /dev/stdout;
  error_log /dev/stderr warn;
  client_body_temp_path /tmp/client;
  proxy_temp_path /tmp/proxy;
  fastcgi_temp_path /tmp/fastcgi;
  uwsgi_temp_path /tmp/uwsgi;
  scgi_temp_path /tmp/scgi;
  server {
    listen 8080;
    client_max_body_size 64m;

    location /minio/ {
      proxy_pass http://{{ printf "%s-minio" .Release.Name }}:9000/;
      proxy_set_header Host $host;
      proxy_buffering off;
    }

    location ~ ^/(search|process-pdf|query-pdf|bigquery|oracle|telco|sqlserver)(/|$) {
      proxy_pass http://{{ printf "%s-python-backend" .Release.Name }}:8000;
      proxy_set_header Host $host;
      proxy_read_timeout 1800s;
      proxy_send_timeout 1800s;
    }

    location /tts/ {
      return 503 "TTS is not installed in this first integration test.\n";
    }

    location / {
      proxy_pass http://{{ printf "%s-frontend" .Release.Name }}:3000;
      proxy_http_version 1.1;
      proxy_set_header Connection "";
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_buffering off;
      proxy_read_timeout 1800s;
      proxy_send_timeout 1800s;
    }
  }
}
{{- end -}}
