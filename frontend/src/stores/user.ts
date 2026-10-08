import {defineStore} from "pinia";
import {requestApi} from "@/utils/request";

const emptyUser = {
    user_id: "",
    name: "",
    email: "",
    phone: "",
    department: "",
    title: "",
    roles: [] as string[],
    active: false,
};

export const useUserStore = defineStore("user", {
    state: () => ({currentUser: {...emptyUser}, mockUserList: [] as (typeof emptyUser)[]}),
    getters: {userId: (state) => state.currentUser.user_id},
    actions: {
        async loadUsers() {
            this.mockUserList = await requestApi<typeof this.mockUserList>({
                baseURL: "/",
                url: "/user/getMockUserList",
                method: "GET",
            });
            if (!this.mockUserList.length) throw new Error("暂无可用用户");
            this.currentUser = this.mockUserList[0]!;
        },
        selectUser(id: string) {
            const user = this.mockUserList.find((item) => item.user_id === id && item.active);
            if (user) this.currentUser = {...user};
        },
    },
});
