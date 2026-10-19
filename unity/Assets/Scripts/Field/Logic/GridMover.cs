using System;

namespace Xnu.Field
{
    // Höhe des Bodens an einer Weltposition (Treppen, Rampen). Im Original über Kollisionsstrahlen
    // (CollisionUtility.CollideGround), hier abstrahiert: in der Szene per Raycast, in Tests synthetisch.
    public interface IGroundHeight
    {
        // fromY: aktuelle Höhe; es wird der Boden bis kurz darüber gesucht. false = kein Boden gefunden.
        bool TryGetHeight(float worldX, float worldZ, float fromY, out float y);
    }

    public sealed class FlatGround : IGroundHeight
    {
        public readonly float Y;
        public FlatGround(float y = 0f) { Y = y; }
        public bool TryGetHeight(float worldX, float worldZ, float fromY, out float y) { y = Y; return true; }
    }

    [Flags]
    public enum MoveEvents
    {
        None = 0,
        Started = 1,    // Schritt zur Nachbarzelle begonnen
        Arrived = 2,    // Zielzelle erreicht
        Bumped = 4,     // Schritt abgelehnt (Kollision), nur gedreht
    }

    // Rasterbewegung des Spielers: ein Schritt = eine Zelle mit fester Geschwindigkeit (Zellen/s).
    // Richtungswechsel nur an Zellgrenzen; gehaltene Richtung verkettet Schritte ohne Pause.
    // Zeitschritt kommt vom Aufrufer (Spiel: feste 30 Hz).
    public sealed class GridMover
    {
        public const float DefaultWalkSpeed = 3.7f;    // FieldCommonParam[0]
        public const float DefaultRunSpeed = 7.14f;    // FieldCommonParam[1]

        readonly FieldCollision _collision;
        readonly IGroundHeight _ground;

        int _targetX, _targetY;
        float _progress;

        public int GridX { get; private set; }
        public int GridY { get; private set; }
        public bool IsMoving { get; private set; }
        public MoveDir Facing { get; private set; } = MoveDir.Down;
        public BlockReason LastBlock { get; private set; }
        public float Height { get; private set; }
        public float WalkSpeed { get; set; } = DefaultWalkSpeed;
        public float RunSpeed { get; set; } = DefaultRunSpeed;
        public bool Bicycle { get; set; }
        public bool Swim { get; set; }
        public long StepsTaken { get; private set; }

        public GridMover(FieldCollision collision, IGroundHeight ground, int gridX, int gridY, MoveDir facing = MoveDir.Down)
        {
            _collision = collision ?? throw new ArgumentNullException(nameof(collision));
            _ground = ground ?? new FlatGround();
            Teleport(gridX, gridY, facing);
        }

        public void Teleport(int gridX, int gridY, MoveDir facing)
        {
            GridX = gridX; GridY = gridY; _targetX = gridX; _targetY = gridY;
            IsMoving = false; _progress = 0f;
            if (facing != MoveDir.None) Facing = facing;
            Height = SampleHeight(WorldX, WorldZ, Height);
        }

        public float Progress => IsMoving ? _progress : 0f;
        public float WorldX => FieldCoords.WorldX(GridX) + (FieldCoords.WorldX(_targetX) - FieldCoords.WorldX(GridX)) * Progress;
        public float WorldZ => FieldCoords.WorldZ(GridY) + (FieldCoords.WorldZ(_targetY) - FieldCoords.WorldZ(GridY)) * Progress;
        public int TargetX => _targetX;
        public int TargetY => _targetY;

        float SampleHeight(float x, float z, float from) => _ground.TryGetHeight(x, z, from, out var y) ? y : from;

        public MoveEvents Tick(float dt, MoveDir held, bool run)
        {
            var events = MoveEvents.None;
            var remaining = dt;
            // Schutz gegen Endlosschleifen bei großem dt: höchstens eine Handvoll Zellen je Tick.
            for (var guard = 0; guard < 16 && remaining > 0f; guard++)
            {
                if (!IsMoving)
                {
                    if (held == MoveDir.None) break;
                    Facing = held;
                    var d = held.GridDelta();
                    var nx = GridX + d.Dx;
                    var ny = GridY + d.Dy;
                    var res = _collision.CanEnter(nx, ny, Height, Bicycle, Swim);
                    if (!res.CanEnter)
                    {
                        LastBlock = res.Reason;
                        events |= MoveEvents.Bumped;
                        break;
                    }
                    LastBlock = BlockReason.None;
                    _targetX = nx; _targetY = ny; _progress = 0f; IsMoving = true;
                    events |= MoveEvents.Started;
                }

                var speed = run ? RunSpeed : WalkSpeed;
                if (speed <= 0f) break;
                var need = (1f - _progress) / speed;
                if (remaining >= need)
                {
                    remaining -= need;
                    GridX = _targetX; GridY = _targetY; _progress = 0f; IsMoving = false;
                    StepsTaken++;
                    events |= MoveEvents.Arrived;
                }
                else
                {
                    _progress += remaining * speed;
                    remaining = 0f;
                }
            }

            Height = SampleHeight(WorldX, WorldZ, Height);
            return events;
        }
    }
}
