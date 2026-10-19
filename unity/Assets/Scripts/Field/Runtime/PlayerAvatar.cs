using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;
using Xnu.Boot;

namespace Xnu.Field
{
    public enum AvatarState
    {
        Idle,
        Walk,
        Run,
    }

    // Spielerfigur aus dem Charakter-Bundle (z. B. Characters/persons/field/fc0001_00): Prefab instanziieren, Materialien
    // sofort ersetzen (Originalmaterialien tragen nur den Fehlershader und werden nie gezeichnet), Animationsclips
    // (idling_f, walk_f, run_f) über einen PlayableGraph mischen (kein AnimatorController im Bundle).
    // Das Modell kommt aus den lokalen Bundles und wird nur zur Laufzeit geladen; nichts davon liegt im Repo.
    public sealed class PlayerAvatar
    {
        public const string IdleClip = "idling_f";
        public const string WalkClip = "walk_f";
        public const string RunClip = "run_f";
        // Zielhöhe der Figur in Zellen (Annahme; Originalmaß nicht ermittelt).
        public const float TargetHeight = 1.4f;
        public float ScaledFrom { get; private set; }

        readonly BundleProvider _provider;
        readonly string _bundleName;
        PlayableGraph _graph;
        AnimationMixerPlayable _mixer;
        readonly float[] _weights = new float[3];
        AvatarState _state = AvatarState.Idle;
        bool _graphValid;

        public GameObject Root { get; private set; }
        public string Note { get; private set; } = "";
        public int Renderers { get; private set; }
        public int ClipsFound { get; private set; }
        public Bounds Bounds { get; private set; }
        public AvatarState State => _state;
        public float FadeSeconds { get; set; } = 0.15f;

        PlayerAvatar(BundleProvider provider, string bundleName)
        {
            _provider = provider; _bundleName = bundleName;
        }

        // null bei Fehlern (Beschreibung in note); der Aufrufer bleibt dann bei der Kapsel.
        public static PlayerAvatar Create(BundleProvider provider, IMapMaterialSource materials, string bundleName, Transform parent, out string note)
        {
            var a = new PlayerAvatar(provider, bundleName);
            try
            {
                var handle = provider.Acquire(bundleName);
                GameObject prefab = null;
                var clips = new Dictionary<string, AnimationClip>(StringComparer.Ordinal);
                foreach (var n in handle.GetAllAssetNames())
                {
                    if (prefab == null && n.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
                        prefab = handle.LoadAsset(n, typeof(GameObject)) as GameObject;
                    else if (n.EndsWith(".anim", StringComparison.OrdinalIgnoreCase))
                    {
                        var c = handle.LoadAsset(n, typeof(AnimationClip)) as AnimationClip;
                        if (c != null) clips[c.name] = c;
                    }
                }
                if (prefab == null) { note = "Kein Prefab in " + bundleName; a.Release(); return null; }

                a.Root = UnityEngine.Object.Instantiate(prefab, parent, false);
                a.Root.name = "PlayerModel";
                a.Root.hideFlags = HideFlags.DontSave;
                // Sofort alle Materialien ersetzen, bevor ein Bild gezeichnet wird.
                var b = new Bounds();
                var first = true;
                foreach (var r in a.Root.GetComponentsInChildren<Renderer>(true))
                {
                    var src = r.sharedMaterials;
                    var dst = new Material[src.Length];
                    for (var i = 0; i < dst.Length; i++) dst[i] = materials.For(src[i]);
                    r.sharedMaterials = dst;
                    a.Renderers++;
                    if (first) { b = r.bounds; first = false; } else b.Encapsulate(r.bounds);
                }
                a.Bounds = b;
                // Modellhöhe: das Modell kommt in anderer Größe als die Rasterzelle; auf Zielhöhe skalieren (Annahme, siehe Doku).
                if (b.size.y > 0.01f && Math.Abs(b.size.y - TargetHeight) > 0.05f)
                {
                    a.Root.transform.localScale *= TargetHeight / b.size.y;
                    a.ScaledFrom = b.size.y;
                }
                a.SetupAnimation(clips);
                note = "Modell " + bundleName + ": " + a.Renderers + " Renderer, " + a.ClipsFound + "/3 Clips, Höhe " + b.size.y.ToString("F2") +
                       (a.ScaledFrom > 0f ? " (auf " + TargetHeight.ToString("F1") + " skaliert)" : "");
                a.Note = note;
                return a;
            }
            catch (Exception e)
            {
                note = "Spielermodell nicht ladbar: " + e.Message;
                a.Destroy();
                return null;
            }
        }

        void SetupAnimation(Dictionary<string, AnimationClip> clips)
        {
            var animator = Root.GetComponentInChildren<Animator>();
            if (animator == null) return;
            animator.runtimeAnimatorController = null;
            animator.applyRootMotion = false;
            var names = new[] { IdleClip, WalkClip, RunClip };
            _graph = PlayableGraph.Create("PlayerAvatar");
            _graph.SetTimeUpdateMode(DirectorUpdateMode.GameTime);
            _mixer = AnimationMixerPlayable.Create(_graph, 3);
            for (var i = 0; i < 3; i++)
            {
                if (!clips.TryGetValue(names[i], out var clip) && !(i == 2 && clips.TryGetValue(WalkClip, out clip))) continue;
                var cp = AnimationClipPlayable.Create(_graph, clip);
                cp.SetApplyFootIK(false);
                _graph.Connect(cp, 0, _mixer, i);
                _mixer.SetInputWeight(i, i == 0 ? 1f : 0f);
                if (clips.ContainsKey(names[i])) ClipsFound++;
            }
            _weights[0] = 1f;
            var output = AnimationPlayableOutput.Create(_graph, "Anim", animator);
            output.SetSourcePlayable(_mixer);
            _graph.Play();
            _graphValid = true;
        }

        public void SetState(AvatarState s) => _state = s;

        // Weiche Überblendung der Gewichte (Zeit in Sekunden).
        public void Tick(float dt)
        {
            if (!_graphValid) return;
            var step = FadeSeconds <= 0f ? 1f : Math.Min(1f, dt / FadeSeconds);
            var sum = 0f;
            for (var i = 0; i < 3; i++)
            {
                var goal = i == (int)_state ? 1f : 0f;
                _weights[i] += (goal - _weights[i]) * step;
                sum += _weights[i];
            }
            if (sum <= 0.0001f) sum = 1f;
            for (var i = 0; i < 3; i++) _mixer.SetInputWeight(i, _weights[i] / sum);
        }

        public static AvatarState StateFor(bool moving, bool run) => !moving ? AvatarState.Idle : (run ? AvatarState.Run : AvatarState.Walk);

        void Release()
        {
            try { _provider.Release(_bundleName); } catch (Exception) { }
        }

        public void Destroy()
        {
            if (_graphValid && _graph.IsValid()) _graph.Destroy();
            _graphValid = false;
            if (Root != null) FieldDestroy.Kill(Root);
            Root = null;
            Release();
        }
    }
}
