/* Cost of a closed tour start -> route[0] -> ... -> route[k-1] -> start on a directed table. */
#include <stdio.h>

#define N 5
const int DIST[N][N] = {{0,12,20,25,15},{11,0,9,18,22},{21,8,0,7,16},{24,19,6,0,10},{14,23,17,9,0}};

int tour_cost(int start, const int *route, int k) {
    if (k == 0) return 0;
    int total = DIST[start][route[0]];
    for (int i = 0; i + 1 < k; i++) total += DIST[route[i]][route[i + 1]];
    return total + DIST[route[k - 1]][start];
}

int main(void) {
    int forward[] = {1, 2, 3, 4}, backward[] = {4, 3, 2, 1};
    printf("%d\n%d\n", tour_cost(0, forward, 4), tour_cost(0, backward, 4));
    return 0;
}
