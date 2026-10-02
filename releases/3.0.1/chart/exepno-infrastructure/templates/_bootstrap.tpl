{{- define "exepno.bootstrapRevision" -}}
{{- printf "%s%s%s" (.Files.Get "files/bootstrap/contract.cjs") (.Files.Get "files/bootstrap/run.cjs") (.Files.Get "files/bootstrap/wait.cjs") | sha256sum | trunc 8 -}}
{{- end -}}

{{- define "exepno.bootstrapConfig" -}}
{{- printf "%s-init-code-%s" .Release.Name (include "exepno.bootstrapRevision" .) -}}
{{- end -}}

{{- define "exepno.bootstrapEnv" -}}
- name: EXEPNO_CUSTOMER_PROJECT
  value: {{ .Values.deployment.projectId | quote }}
- name: EXEPNO_INSTANCE
  value: {{ .Release.Name | quote }}
- name: EXEPNO_NAMESPACE
  value: {{ .Release.Namespace | quote }}
- name: EXEPNO_INITIAL_ADMIN_UID
  value: {{ .Values.bootstrap.adminUid | quote }}
- name: EXEPNO_MONGO_APP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.existingSecrets.mongoInitialization | quote }}
      key: MONGO_APP_PASSWORD
- name: MINIO_ENDPOINT
  value: {{ printf "%s-minio" .Release.Name | quote }}
- name: MINIO_PORT
  value: "9000"
- name: MINIO_USE_SSL
  value: "false"
- name: QDRANT_HOST
  value: {{ printf "%s-qdrant" .Release.Name | quote }}
- name: QDRANT_PORT
  value: "6333"
{{- end -}}

{{- define "exepno.bootstrapGate" -}}
[
  {
    "name": "wait-for-initialization",
    "image": {{ index .Values.components "frontend" "image" | toJson }},
    "command": ["node", "/bootstrap/wait.cjs"],
    "envFrom": [
      {"secretRef":{"name":{{ .Values.existingSecrets.runtime | toJson }}}}
    ],
    "env": {{ include "exepno.bootstrapEnv" . | fromYamlArray | toJson }},
    "volumeMounts": [
      {"name":"bootstrap-code","mountPath":"/bootstrap","readOnly":true}
    ],
    "securityContext": {
      "allowPrivilegeEscalation":false,
      "readOnlyRootFilesystem":true,
      "capabilities":{"drop":["ALL"]}
    },
    "resources": {
      "requests":{"cpu":"50m","memory":"96Mi"},
      "limits":{"cpu":"500m","memory":"256Mi"}
    }
  }
]
{{- end -}}
