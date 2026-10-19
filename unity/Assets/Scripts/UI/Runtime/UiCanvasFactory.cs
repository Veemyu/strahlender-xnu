using UnityEngine;
using UnityEngine.UI;

namespace Xnu.UI
{
    // Canvas wie im Original: Skalierung "Scale With Screen Size", Referenz 1280x720, Abgleich nach Breite (Match 0).
    // Sortierwerte (UIManager): Fenster 400, Kontextmenü 9900, Übergang 16384.
    public static class UiCanvasFactory
    {
        public const float ReferenceWidth = 1280f;
        public const float ReferenceHeight = 720f;
        public const int SortingWindow = 400;

        // Mit Kamera: Screen Space - Camera (folgt dem 16:9-Ausschnitt des DisplayController); ohne: Overlay.
        public static Canvas Create(string name, Camera camera, int sortingOrder, Transform parent = null)
        {
            var go = new GameObject(name, typeof(RectTransform));
            if (parent != null) go.transform.SetParent(parent, false);
            var canvas = go.AddComponent<Canvas>();
            if (camera != null)
            {
                canvas.renderMode = RenderMode.ScreenSpaceCamera;
                canvas.worldCamera = camera;
                canvas.planeDistance = 1f;
            }
            else canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = sortingOrder;

            var scaler = go.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(ReferenceWidth, ReferenceHeight);
            scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            scaler.matchWidthOrHeight = 0f;
            return canvas;
        }
    }
}
