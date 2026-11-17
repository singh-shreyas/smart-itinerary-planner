/* Stable merge sort of places by (score descending, id ascending). */
#include <stdio.h>
#include <string.h>

typedef struct { int id, score; } Place;

int before(Place a, Place b) {               /* key comparison: "a <= b" in sort order */
    if (a.score != b.score) return a.score > b.score;
    return a.id <= b.id;
}

void merge_sort(Place *a, Place *tmp, int lo, int hi) {   /* sorts a[lo..hi) */
    if (hi - lo <= 1) return;
    int mid = (lo + hi) / 2;
    merge_sort(a, tmp, lo, mid);
    merge_sort(a, tmp, mid, hi);
    int i = lo, j = mid, k = lo;
    while (i < mid && j < hi) tmp[k++] = before(a[i], a[j]) ? a[i++] : a[j++];  /* left wins ties */
    while (i < mid) tmp[k++] = a[i++];
    while (j < hi) tmp[k++] = a[j++];
    memcpy(a + lo, tmp + lo, (size_t)(hi - lo) * sizeof *a);
}

int main(void) {
    Place p[] = {{101, 72}, {102, 90}, {103, 72}, {104, 55}, {105, 90}}, tmp[5];
    merge_sort(p, tmp, 0, 5);
    for (int i = 0; i < 5; i++) printf("%d ", p[i].id);
    printf("\n");
    return 0;
}
