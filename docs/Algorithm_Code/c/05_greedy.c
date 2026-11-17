/* Greedy knapsack selection by value per time unit (the fast baseline). */
#include <stdio.h>
#include <stdlib.h>

typedef struct { char id; int score, weight; } Item;

int by_density(const void *pa, const void *pb) {     /* higher score/weight first, then id */
    const Item *a = pa, *b = pb;
    long lhs = (long)a->score * b->weight, rhs = (long)b->score * a->weight;  /* no floats */
    if (lhs != rhs) return lhs > rhs ? -1 : 1;
    return a->id - b->id;
}

int main(void) {
    Item items[] = {{'X', 90, 18}, {'Y', 60, 15}, {'Z', 60, 15}};  /* the greedy trap */
    int n = 3, cap = 30, used = 0, total = 0;
    qsort(items, n, sizeof *items, by_density);       /* project uses its own merge sort */
    printf("chosen:");
    for (int i = 0; i < n; i++)
        if (used + items[i].weight <= cap) {
            used += items[i].weight; total += items[i].score;
            printf(" %c", items[i].id);
        }
    printf("  value %d\n", total);
    return 0;
}
