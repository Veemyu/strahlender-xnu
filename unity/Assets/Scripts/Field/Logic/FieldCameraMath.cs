using System;

namespace Xnu.Field
{
    // Kameravorgaben je Gebiet (MapInfo.Camera, nach AreaID): Neigung, Sichtfeld, Abstand zum Ziel.
    public readonly struct FieldCameraSettings
    {
        public readonly float PitchDegrees;
        public readonly float FovDegrees;
        public readonly float TargetRange;

        public FieldCameraSettings(float pitchDegrees, float fovDegrees, float targetRange)
        {
            PitchDegrees = pitchDegrees; FovDegrees = fovDegrees; TargetRange = targetRange;
        }
    }

    // Kamerapose nach FieldCamera.CameraUpdate: Euler = (Neigung, Gier, 0) + Versatzwinkel; Brennpunkt =
    // Ziel + Versatz + (0, 0.5, 0); Position = Brennpunkt - Blickrichtung * Abstand. Gier ist im Normalfall 0
    // (Blick nach +Z), 180 bei gesetztem Systemflag 0x305.
    public static class FieldCameraMath
    {
        public const float FocusHeight = 0.5f;

        public static (float X, float Y, float Z) Forward(float pitchDegrees, float yawDegrees)
        {
            var p = pitchDegrees * (float)Math.PI / 180f;
            var y = yawDegrees * (float)Math.PI / 180f;
            var cp = (float)Math.Cos(p);
            return ((float)Math.Sin(y) * cp, -(float)Math.Sin(p), (float)Math.Cos(y) * cp);
        }

        public static (float X, float Y, float Z) Focus(float targetX, float targetY, float targetZ,
            float offsetX = 0f, float offsetY = 0f, float offsetZ = 0f)
            => (targetX + offsetX, targetY + offsetY + FocusHeight, targetZ + offsetZ);

        public static (float X, float Y, float Z) Position((float X, float Y, float Z) focus, float pitchDegrees, float yawDegrees, float targetRange)
        {
            var f = Forward(pitchDegrees, yawDegrees);
            return (focus.X - f.X * targetRange, focus.Y - f.Y * targetRange, focus.Z - f.Z * targetRange);
        }

        // Weiches Nachführen des Brennpunkts: Lerp mit Rate * dt (begrenzt auf 1).
        public static (float X, float Y, float Z) Follow((float X, float Y, float Z) current, (float X, float Y, float Z) goal, float rate, float dt)
        {
            var t = Math.Max(0f, Math.Min(1f, rate * dt));
            return (current.X + (goal.X - current.X) * t, current.Y + (goal.Y - current.Y) * t, current.Z + (goal.Z - current.Z) * t);
        }
    }
}
