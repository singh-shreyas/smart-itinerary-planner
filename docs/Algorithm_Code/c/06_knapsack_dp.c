/* 0/1 knapsack over the day's time units, with traceback. */
#include <stdio.h>

#define MAXN 16
#define MAXT 64

typedef struct { char id; int score, weight; } Item;

int dp_select(const Item *items, int n, int T, char *chosen, int *count) {
    static int best[MAXN + 1][MAXT + 1];                 /* best[i][t] */
    for (int t = 0; t <= T; t++) best[0][t] = 0;
    for (int i = 1; i <= n; i++) {
        int w = items[i - 1].weight, s = items[i - 1].score;
        for (int t = 0; t <= T; t++) {
            int skip = best[i - 1][t];
            int take = (w <= t) ? s + best[i - 1][t - w] : -1;
            best[i][t] = take > skip ? take : skip;
        }
    }
    int t = T, k = 0;
    for (int i = n; i >= 1; i--)                          /* walk the table backwards */
        if (best[i][t] != best[i - 1][t]) { chosen[k++] = items[i - 1].id; t -= items[i - 1].weight; }
    for (int a = 0, b = k - 1; a < b; a++, b--) { char c = chosen[a]; chosen[a] = chosen[b]; chosen[b] = c; }
    *count = k;
    return best[n][T];
}

void run(const Item *items, int n, int T) {
    char chosen[MAXN]; int k;
    int value = dp_select(items, n, T, chosen, &k);
    printf("chosen:");
    for (int i = 0; i < k; i++) printf(" %c", chosen[i]);
    printf("  value %d\n", value);
}

int main(void) {
    Item trap[] = {{'X', 90, 18}, {'Y', 60, 15}, {'Z', 60, 15}};
    Item dry[]  = {{'A', 90, 3}, {'B', 50, 2}, {'C', 50, 2}};
    run(trap, 3, 30);
    run(dry, 3, 4);
    return 0;
}
