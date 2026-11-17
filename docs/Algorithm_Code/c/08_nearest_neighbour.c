/* Nearest Neighbour: from the stay, always go to the closest unvisited stop. */
#include <stdio.h>

#define N 5
const int DIST[N][N] = {{0,12,20,25,15},{11,0,9,18,22},{21,8,0,7,16},{24,19,6,0,10},{14,23,17,9,0}};

void nearest_neighbour(int start, const int *stops, int k, int *route) {
    int used[N] = {0}, current = start;
    for (int step = 0; step < k; step++) {
        int best = -1;
        for (int i = 0; i < k; i++) {
            int s = stops[i];
            if (used[s]) continue;
            if (best == -1 || DIST[current][s] < DIST[current][best] ||
                (DIST[current][s] == DIST[current][best] && s < best)) best = s;   /* ties: smaller id */
        }
        used[best] = 1; route[step] = best; current = best;
    }
}

int main(void) {
    int stops[] = {1, 2, 3, 4}, route[4];
    nearest_neighbour(0, stops, 4, route);
    for (int i = 0; i < 4; i++) printf("%d ", route[i]);
    printf("\n");
    return 0;
}
