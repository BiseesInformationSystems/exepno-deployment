{{- define "exepno.bootstrapJobSpec" -}}
backoffLimit: 0
activeDeadlineSeconds: 1200
template:
  metadata:
    labels:
      app.kubernetes.io/name: {{ .Release.Name | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
  spec:
    restartPolicy: Never
    serviceAccountName: {{ .Values.serviceAccount.name | quote }}
    automountServiceAccountToken: false
    securityContext:
      runAsNonRoot: true
      runAsUser: 1000
      runAsGroup: 1000
      seccompProfile:
        type: RuntimeDefault
    containers:
      - name: bootstrap
        image: {{ index .Values.components "frontend" "image" | quote }}
        command: ["node", "/bootstrap/run.cjs"]
        envFrom:
          - secretRef:
              name: {{ .Values.existingSecrets.runtime | quote }}
        env:
          {{- include "exepno.bootstrapEnv" . | nindent 12 }}
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: "1"
            memory: 512Mi
        volumeMounts:
          - name: code
            mountPath: /bootstrap
            readOnly: true
    volumes:
      - name: code
        configMap:
          name: {{ include "exepno.bootstrapConfig" . | quote }}
{{- end -}}
