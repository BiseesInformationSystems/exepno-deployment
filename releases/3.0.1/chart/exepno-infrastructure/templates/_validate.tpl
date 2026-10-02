{{- define "exepno.validate" -}}
{{- if or (gt (len .Release.Name) 40) (not (regexMatch "^[a-z][a-z0-9-]*[a-z0-9]$" .Release.Name)) -}}
{{- fail "Use an application name of 2-40 lowercase letters/digits/hyphens." -}}
{{- end -}}
{{- end -}}
