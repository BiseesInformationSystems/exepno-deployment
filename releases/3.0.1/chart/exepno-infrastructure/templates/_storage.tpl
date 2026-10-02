{{- define "exepno.claimName" -}}
{{- $storage := index .root.Values.persistence .name -}}
{{- default (printf "%s-%s" .root.Release.Name .name) $storage.existingClaim -}}
{{- end -}}
