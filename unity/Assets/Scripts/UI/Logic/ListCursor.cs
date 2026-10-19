using System;

namespace Xnu.UI
{
    // Cursor einer senkrechten Liste mit sichtbarem Ausschnitt (Beutel-Liste, Party, Menü): Index, Seitengröße, Umlauf.
    // Ohne Unity-Typen. Top = erster sichtbarer Eintrag.
    public sealed class ListCursor
    {
        public int Count { get; private set; }
        public int PageSize { get; }
        public bool Wrap { get; }
        public int Index { get; private set; }
        public int Top { get; private set; }

        public ListCursor(int count, int pageSize, bool wrap = false)
        {
            if (count < 0) throw new ArgumentOutOfRangeException(nameof(count));
            if (pageSize <= 0) throw new ArgumentOutOfRangeException(nameof(pageSize));
            Count = count;
            PageSize = pageSize;
            Wrap = wrap;
        }

        public int VisibleCount => Math.Max(0, Math.Min(PageSize, Count - Top));
        public bool HasMoreAbove => Top > 0;
        public bool HasMoreBelow => Top + PageSize < Count;

        // Neue Länge (z. B. andere Tasche); Cursor und Ausschnitt werden eingepasst.
        public void SetCount(int count)
        {
            if (count < 0) throw new ArgumentOutOfRangeException(nameof(count));
            Count = count;
            Index = Count == 0 ? 0 : Math.Min(Index, Count - 1);
            Top = Math.Max(0, Math.Min(Top, Math.Max(0, Count - PageSize)));
            Fit();
        }

        public void Reset()
        {
            Index = 0;
            Top = 0;
        }

        public void Set(int index)
        {
            if (Count == 0) return;
            Index = Math.Max(0, Math.Min(Count - 1, index));
            Fit();
        }

        // Bewegt um delta (negativ = nach oben). true, wenn sich der Index geändert hat.
        public bool Move(int delta)
        {
            if (Count == 0 || delta == 0) return false;
            var old = Index;
            var next = Index + delta;
            if (Wrap)
            {
                next %= Count;
                if (next < 0) next += Count;
            }
            else next = Math.Max(0, Math.Min(Count - 1, next));
            Index = next;
            Fit();
            return Index != old;
        }

        void Fit()
        {
            if (Index < Top) Top = Index;
            else if (Index >= Top + PageSize) Top = Index - PageSize + 1;
            Top = Math.Max(0, Math.Min(Top, Math.Max(0, Count - PageSize)));
        }
    }

    // Cursor eines Rasters (Hauptmenü): Spaltenzahl fest, Bewegung nach links/rechts/oben/unten ohne Umlauf über die Zeilen hinaus;
    // eine unvollständige letzte Zeile wird beim Hinabgehen auf den letzten Eintrag begrenzt.
    public sealed class GridCursor
    {
        public int Count { get; }
        public int Columns { get; }
        public int Index { get; private set; }

        public GridCursor(int count, int columns, int initial = 0)
        {
            if (count <= 0) throw new ArgumentOutOfRangeException(nameof(count));
            if (columns <= 0) throw new ArgumentOutOfRangeException(nameof(columns));
            if (initial < 0 || initial >= count) throw new ArgumentOutOfRangeException(nameof(initial));
            Count = count;
            Columns = columns;
            Index = initial;
        }

        public int Row => Index / Columns;
        public int Column => Index % Columns;
        public int Rows => (Count + Columns - 1) / Columns;

        public bool Move(int dx, int dy)
        {
            var old = Index;
            if (dx != 0)
            {
                var col = Column + (dx > 0 ? 1 : -1);
                var next = Row * Columns + col;
                if (col >= 0 && col < Columns && next < Count) Index = next;
            }
            if (dy != 0)
            {
                var row = Row + (dy > 0 ? 1 : -1);
                if (row >= 0 && row < Rows) Index = Math.Min(Count - 1, row * Columns + Column);
            }
            return Index != old;
        }

        public void Set(int index) => Index = Math.Max(0, Math.Min(Count - 1, index));
    }
}
