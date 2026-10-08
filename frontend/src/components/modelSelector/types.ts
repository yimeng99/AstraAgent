export type Model = {
  id: string;
  name: string;
  description: string;
};

export type Provider = Model & {
  children: Model[];
};

export type ModelList = {
  default: Model;
  providers: Provider[];
};
