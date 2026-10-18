using UnityEngine;

namespace Xnu.Core.Display
{
    // Wendet Seitenverhältnis und Bildrate auf die laufende Anwendung an.
    // Die Kamera wird per Rect auf das Zielverhältnis begrenzt; ein Hintergrund-Kamera-Objekt
    // (schwarz, Tiefe -100) füllt die Balken.
    [DisallowMultipleComponent]
    public sealed class DisplayController : MonoBehaviour
    {
        public AspectMode Aspect = AspectMode.Aspect16x9;
        public FrameRateMode FrameRate = FrameRateMode.Fixed60;
        public Camera TargetCamera;

        private int _lastWidth, _lastHeight;

        private void Awake()
        {
            ApplyFrameRate();
            ApplyViewport(force: true);
        }

        private void Update()
        {
            if (Screen.width != _lastWidth || Screen.height != _lastHeight) ApplyViewport(force: true);
        }

        public void ApplyFrameRate()
        {
            var hz = Mathf.Max(1, Mathf.RoundToInt((float)Screen.currentResolution.refreshRateRatio.value));
            var plan = FrameRatePlanner.Plan(FrameRate, hz);
            QualitySettings.vSyncCount = plan.VSyncCount;
            Application.targetFrameRate = plan.TargetFrameRate;
        }

        public void ApplyViewport(bool force)
        {
            _lastWidth = Screen.width;
            _lastHeight = Screen.height;
            if (TargetCamera == null) TargetCamera = Camera.main;
            if (TargetCamera == null) return;

            var r = AspectMath.Fit(Screen.width, Screen.height, Aspect);
            TargetCamera.rect = new Rect(r.X, r.Y, r.Width, r.Height);
        }
    }
}
