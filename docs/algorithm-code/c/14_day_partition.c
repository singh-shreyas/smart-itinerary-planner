/* Spreading places over days: even target, then best-fit construction and local search
   (relocate one place, or swap two) until no move lowers the cost.
   Stand-in feasibility: a day holds at most 300 minutes. */
#include <stdio.h>
#include <stdlib.h>

#define P 5
#define D 3
const char NAME[P] = {'A', 'B', 'C', 'D', 'E'};
const int MIN[P] = {120, 90, 150, 60, 90};
int target[D];

void target_counts(int n, int days, int *t) {
    int base = n / days, extra = n % days;
    for (int d = 0; d < days; d++) t[d] = base;
    if (base == 0) {
        for (int k = 0; k < extra; k++) {
            int idx = (extra == 1) ? 0 : (int)((double)k * (days - 1) / (extra - 1) + 0.5);
            t[idx]++;
        }
    } else {
        for (int k = 0; k < extra; k++) t[k]++;
    }
}

int desc(const void *a, const void *b) { return *(const int *)b - *(const int *)a; }

int feasible(const int *day_of) {
    int load[D] = {0};
    for (int p = 0; p < P; p++) if (day_of[p] >= 0) load[day_of[p]] += MIN[p];
    for (int d = 0; d < D; d++) if (load[d] > 300) return 0;
    return 1;
}

/* cost = unplaced * 100 + deviation from the target (both lists sorted descending) */
int cost(const int *day_of) {
    int counts[D] = {0}, tg[D], unplaced = 0, dev = 0;
    for (int p = 0; p < P; p++) { if (day_of[p] < 0) unplaced++; else counts[day_of[p]]++; }
    for (int d = 0; d < D; d++) tg[d] = target[d];
    qsort(counts, D, sizeof(int), desc); qsort(tg, D, sizeof(int), desc);
    for (int d = 0; d < D; d++) dev += abs(counts[d] - tg[d]);
    return unplaced * 100 + dev;
}

int main(void) {
    int day_of[P], order[P] = {2, 0, 1, 4, 3};       /* longest first, ties by name */
    target_counts(P, D, target);
    printf("target: %d %d %d\n", target[0], target[1], target[2]);
    for (int p = 0; p < P; p++) day_of[p] = -1;

    for (int i = 0; i < P; i++) {                     /* construct: best feasible day */
        int p = order[i], best_day = -1, best_cost = 0;
        for (int d = 0; d < D; d++) {
            day_of[p] = d;
            if (feasible(day_of) && (best_day < 0 || cost(day_of) < best_cost)) { best_day = d; best_cost = cost(day_of); }
        }
        day_of[p] = best_day;
    }

    for (int improved = 1; improved;) {               /* improve: first improving move */
        improved = 0;
        int now = cost(day_of);
        for (int p = 0; p < P && !improved; p++)      /* relocate */
            for (int d = 0; d < D && !improved; d++) {
                int old = day_of[p];
                if (d == old) continue;
                day_of[p] = d;
                if (feasible(day_of) && cost(day_of) < now) improved = 1; else day_of[p] = old;
            }
        for (int p = 0; p < P && !improved; p++)      /* swap */
            for (int q = p + 1; q < P && !improved; q++) {
                if (day_of[p] == day_of[q] || day_of[p] < 0 || day_of[q] < 0) continue;
                int t = day_of[p]; day_of[p] = day_of[q]; day_of[q] = t;
                if (feasible(day_of) && cost(day_of) < now) improved = 1;
                else { t = day_of[p]; day_of[p] = day_of[q]; day_of[q] = t; }
            }
    }
    for (int d = 0; d < D; d++) {
        printf("day %d:", d + 1);
        for (int p = 0; p < P; p++) if (day_of[p] == d) printf(" %c", NAME[p]);
        printf("\n");
    }
    printf("cost: %d\n", cost(day_of));
    return 0;
}
